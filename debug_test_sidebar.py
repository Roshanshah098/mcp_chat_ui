import streamlit as st
import time

st.set_page_config(page_title="Sidebar Slow-Load Test", layout="wide")

st.write("## Main area")
st.write(
    "This is the EXACT same debug_sidebar.py that already worked for you, "
    "with ONE change: a 20-second delay added before the sidebar renders, "
    "to isolate whether a slow load (not CSS, not JS, not query_params) "
    "is what breaks aria-expanded."
)
st.write("Waiting 20 seconds to simulate your real app's backend boot…")

# Show a simple progress indicator so you know it's working, not frozen
progress = st.progress(0)
for i in range(20):
    time.sleep(1)
    progress.progress((i + 1) / 20)

st.write("Done waiting. Sidebar should appear on the left now.")

with st.sidebar:
    st.markdown(
        "<div style='background:red;color:white;padding:20px;"
        "font-size:24px;font-weight:bold'>IT WORKS</div>",
        unsafe_allow_html=True,
    )
    st.write("Plain sidebar text")
    st.button("Plain button")

import streamlit

print(f"\n\n[DEBUG] Streamlit version: {streamlit.__version__}\n\n")
st.sidebar.caption(f"Streamlit version: {streamlit.__version__}")
