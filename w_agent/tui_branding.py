"""Terminal-only welcome artwork; no fonts, images, or network assets."""

from rich.cells import cell_len
from rich.text import Text


_LOGO = (
    "██╗    ██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    "██║    ██║      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    "██║ █╗ ██║█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
    "██║███╗██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
    "╚███╔███╔╝      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
    " ╚══╝╚══╝       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
)


def welcome_banner(width: int, version: str) -> Text:
    """Choose intact artwork using terminal-cell width, not character count."""
    art_width = max(cell_len(line) for line in _LOGO)
    result = Text(justify="center", no_wrap=True, overflow="crop")
    if width >= art_width:
        for index, line in enumerate(_LOGO):
            result.append(line.ljust(art_width), "bold cyan" if index < 3 else "cyan")
            result.append("\n")
    else:
        result.append("W-AGENT\n", "bold cyan")
    mascot = "(づ｡◕‿‿◕｡)づ  Let's build something lovely!"
    if cell_len(mascot) > width:
        mascot = "(｡•ᴗ•｡)" if width >= cell_len("(｡•ᴗ•｡)") else ":)"
    result.append(f"\n{mascot}\n", "bold magenta")
    tagline = f"local · open · yours   /   v{version}"
    if cell_len(tagline) <= width:
        result.append(tagline, "dim")
    return result
