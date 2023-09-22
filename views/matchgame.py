import discord, asyncio
import functions as func

from iufi import (
    Card,
    TempCard,
    CardPool,
    gen_cards_view
)
from discord.ext import commands
from random import shuffle
from typing import Any
from collections import Counter
from . import ButtonOnCooldown

GAME_SETTINGS: dict[str, dict[str, Any]] = {
    "1": {
        "cooldown": 600,
        "timeout": 200,
        "cover_img": "cover/level1.jpg",
        "cards": 3,
        "elem_per_row": 3,
        "rewards": [None, None, None],
    },
    "2": {
        "cooldown": 900,
        "timeout": 300,
        "cover_img": "cover/level2.jpg",
        "cards": 4,
        "elem_per_row": 4,
        "rewards": [None, None, None],
    }
}

def key(interaction: discord.Interaction):
    return interaction.user

class GuessButton(discord.ui.Button):
    def __init__(self, card: Card, *args, **kwargs) -> None:
        self.view: MatchGame

        self.card: Card = card
        super().__init__(*args, **kwargs)
    
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view._need_wait:
            return await interaction.response.send_message("Too fast. Please slower!", ephemeral=True)
        
        await interaction.response.defer()
        await self.handle_matching()
        
    async def handle_matching(self):
        if self.view._is_matching:
            await self.matching_process()
        else:
            self.view.guessed[self.custom_id] = self.card
            self.disabled = True

        self.view._is_matching = not self.view._is_matching
        self.view._last_clicked = self
        self.view.clicked += 1
        
        if self.view.click_left <= 0:
            await self.view.end_game()
            
        elif self.view.matched() >= self.view._cards:
            await self.view.end_game()
        
        embed, file = self.view.build()
        await self.view.response.edit(embed=embed, attachments=[file], view=self.view)

    async def matching_process(self):
        for card in self.view.guessed.values():
            if card == self.card:
                self.view.guessed[self.custom_id] = self.card
                self.disabled = True
                break
        else:
            self.disabled = True
            self.view.guessed[self.custom_id] = self.card

            embed, file = self.view.build()
            await self.view.response.edit(embed=embed, attachments=[file], view=self.view)
            self.view._need_wait = True
            
            await asyncio.sleep(5)
            self.reset_cards()

    def reset_cards(self):
        # Reset the last clicked card and current card to covered state
        self.view._last_clicked.disabled = False
        self.view.guessed[self.view._last_clicked.custom_id] = self.view.covered_card
        self.view.guessed[self.custom_id] = self.view.covered_card

        # Allow the next click
        self.view._need_wait = False
        # Enable the current button again for the next round of guessing
        self.disabled = False

class MatchGame(discord.ui.View):
    def __init__(self, author: discord.Member, level: str = "1", timeout: float = None):
        super().__init__(timeout=timeout)

        self.author: discord.Member = author
        self._level: str = level
        self._data: dict[str, Any] = GAME_SETTINGS.get(level)
        self._cards: int = self._data.get("cards")
        self._max_click: int = (self._cards * 2) + 2
        
        self._is_matching: bool = False
        self._need_wait: bool = False
        self.clicked: int = 0
        self._last_clicked: discord.ui.Button = None
        self.covered_card: TempCard = TempCard(self._data.get("cover_img"))

        cards: list[Card] = CardPool.roll(self._cards)
        cards.extend(cards)
        self.cards: list[Card] = cards
        shuffle(self.cards)

        self.guessed: dict[str, Card] = {}
        self.embed_color = discord.Color.random()
        self.response: discord.Message = None
        self._is_ended: bool = False
        self.cooldown = commands.CooldownMapping.from_cooldown(1.0, 3.0, key)

        for index, card in enumerate(self.cards, start=1):
            index = str(index)

            self.guessed.setdefault(index, self.covered_card)
            self.add_item(GuessButton(card, label=index, custom_id=index, row=(int(index) -1) // self._data.get("elem_per_row")))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            return False
        
        if self._is_ended:
            return False

        retry_after = self.cooldown.update_rate_limit(interaction)
        if retry_after:
            raise ButtonOnCooldown(retry_after)
        return True
    
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        if isinstance(error, ButtonOnCooldown):
            sec = int(error.retry_after)
            await interaction.response.send_message(f"You're on cooldown for {sec} second{'' if sec == 1 else 's'}!", ephemeral=True)
        
    async def timeout_count(self) -> None:
        await asyncio.sleep(self._data.get("timeout", 0))
        await self.end_game()
        await self.response.edit(view=self)
        self.stop()

    async def end_game(self) -> None:
        if self._is_ended:
            return
        self._is_ended = True

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(title="Game Ended (Rewards)", color=discord.Color.random())
        embed.description = "```None```"
        # data = {}
        # for reward in self._data.get("rewards"):
        #     if reward:
        #         data.update(reward)

        # if self.matched() > 0:
        #     await func.update_user(self.author.id, {"$inc": data})
        
        await self.response.channel.send(content=f"<@{self.author.id}>", embed=embed)

    def build(self) -> tuple[discord.Embed, discord.File]:
        embed = discord.Embed(
            description=f"```Level:        {self._level}\n" \
                        f"Click left:   {self.click_left}\n" \
                        f"Card Matched: {self.matched()}```",
            color=self.embed_color
        )   

        bytes, image_format = gen_cards_view([card for card in self.guessed.values()], cards_per_row=self._data.get("elem_per_row"))
        embed.set_image(url=f"attachment://image.{image_format}")

        return embed, discord.File(bytes, filename=f"image.{image_format}")

    def matched(self) -> int:
        counter = Counter([card for card in self.guessed.values() if card != self.covered_card])
        return len([count for count in counter.values() if count == 2])
    
    @property
    def click_left(self) -> int:
        return self._max_click - self.clicked