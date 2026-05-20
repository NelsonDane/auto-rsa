"""UI-agnostic core for the AutoRSA GUI.

Nothing in this package imports Streamlit (or any web framework). It only
exposes plain Python objects: an encrypted credential vault, a 2FA prompt
bus, a log stream, and a trade runner. Any view layer (Streamlit today,
FastAPI later) can sit on top of these.
"""
