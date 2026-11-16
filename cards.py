"""The look of the bot's messages (overhaul 2026-11-16, Shane's pick): Discord's card layout (Components V2).
One card = a Container with an accent bar in a THEME colour, holding text blocks, thin dividers, pictures and rows of
buttons. A card message can't also have plain text or embeds, and an old embed message can't become a card: the bot
sends a new message and deletes the old one.

Build cards from these helpers so every message looks the same:
    card("accent", header("Title", "small line"), divider(), text("**CPU** 8%"), row(button(...)))
"""
from __future__ import annotations

from typing import Awaitable, Callable

import discord
from discord import ui

from common import THEME, OwnerCard

Style = discord.ButtonStyle


def colour(name: str | int) -> int:
    return THEME[name] if isinstance(name, str) else name


def text(*lines: str) -> ui.TextDisplay:
    """A block of Discord markdown (## heading, **bold**, -# small grey line). Empty lines are dropped."""
    return ui.TextDisplay("\n".join(x for x in lines if x))


def header(title: str, sub: str | None = None, thumb: str | None = None, level: int = 2) -> ui.Item:
    """A heading with an optional small grey line under it and an optional picture on the right."""
    body = text(f"{'#' * level} {title}", f"-# {sub}" if sub else "")
    return ui.Section(body, accessory=ui.Thumbnail(thumb)) if thumb else body


def divider(big: bool = False) -> ui.Separator:
    return ui.Separator(spacing=discord.SeparatorSpacing.large if big else discord.SeparatorSpacing.small)


def picture(url: str, description: str | None = None) -> ui.MediaGallery:
    """A full-width picture: a URL, or "attachment://name.png" for a file sent with the message."""
    return ui.MediaGallery(discord.MediaGalleryItem(url, description=description))


def button(label: str, callback: Callable[[discord.Interaction], Awaitable], custom_id: str | None = None,
           style: Style = Style.secondary, emoji: str | None = None) -> ui.Button:
    """A button that runs callback(interaction). Give it a custom_id to keep it working after a restart."""
    b = ui.Button(label=label, custom_id=custom_id, style=style, emoji=emoji)
    b.callback = callback
    return b


def link(label: str, url: str, emoji: str | None = None) -> ui.Button:
    """A button that opens a web page."""
    return ui.Button(label=label, url=url, style=Style.link, emoji=emoji)


def pictures(urls: list[str]) -> ui.MediaGallery:
    """Up to 10 pictures as a grid (one fills the width)."""
    return ui.MediaGallery(*(discord.MediaGalleryItem(u) for u in urls[:10]))


def menu(placeholder: str, options: list[tuple[str, str]], callback: Callable[[discord.Interaction, ui.Select],
         Awaitable], custom_id: str | None = None) -> ui.Select:
    """A drop-down of (label, value) options that runs callback(interaction, select)."""
    s = ui.Select(placeholder=placeholder, custom_id=custom_id,
                  options=[discord.SelectOption(label=label, value=value) for label, value in options])

    async def cb(interaction):
        await callback(interaction, s)
    s.callback = cb
    return s


def row(*items: ui.Item) -> ui.ActionRow:
    return ui.ActionRow(*items)


def card(accent: str | int, *items: ui.Item | None) -> ui.Container:
    """The card itself: items top to bottom (None is skipped), with the accent bar on the left."""
    return ui.Container(*(i for i in items if i is not None), accent_colour=colour(accent))


class Card(OwnerCard):
    """A message holding one or more cards. Buttons on it only answer Shane. timeout=None keeps it alive until the
    bot restarts (persistent cards also need custom_ids and bot.add_view)."""

    def __init__(self, *cards: ui.Container, timeout: float | None = None):
        super().__init__(timeout=timeout)
        for c in cards:
            self.add_item(c)
