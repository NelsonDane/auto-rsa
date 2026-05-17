"""Local web GUI for AutoRSA.

The GUI is split into a UI-agnostic core (``src.gui.core``) and a thin
Streamlit view (``src.gui.app``). The core has no Streamlit imports so a
future pivot to FastAPI only requires replacing the view layer.
"""
