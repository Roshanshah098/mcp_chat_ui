# =============================================================
# — Blog Generator
# =============================================================
import sys
import os
import streamlit as st

st.set_page_config(page_title="Blog Generator", page_icon="📝", layout="wide")

# -- CSS --
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html,body,[data-testid="stAppViewContainer"]{
    background:#080810!important;color:#e2e2f0;font-family:'Inter',sans-serif;
}
[data-testid="stHeader"]{background:transparent!important;}
[data-testid="stToolbar"]{display:none!important;}

[data-testid="stSidebar"] {
    width: 280px !important;
    min-width: 280px !important;
    max-width: 280px !important;
    margin-left: 0 !important;
    transform: none !important;
    transition: none !important;
    background: linear-gradient(180deg,#0a0a14 0%,#0d0d1a 100%) !important;
    border-right: 1px solid #1a1a2e !important;
    visibility: visible !important;
    opacity: 1 !important;
    display: block !important;
    position: relative !important;
    left: 0 !important;
}
[data-testid="stSidebar"] > div:first-child {
    width: 280px !important;
    margin-left: 0 !important;
    transform: none !important;
    position: relative !important;
    left: 0 !important;
}
[data-testid="stSidebar"] div {
    transform: none !important;
    transition: none !important;
}
[data-testid="stSidebar"] * {
    color: #e2e2f0 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button {
    background: transparent !important;
    border: 1px solid #1e1e2e !important;
    border-radius: 10px !important;
    color: #c4c4d8 !important;
    font-size: 13px !important;
    padding: 9px 12px !important;
    transition: all .18s !important;
    width: 100% !important;
    text-align: left !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
    background: rgba(99,102,241,.12) !important;
    border-color: #6366f1 !important;
    color: #a5b4fc !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }

[data-testid="stAppViewContainer"] > section:nth-child(2) {
    margin-left: 280px !important;
    max-width: calc(100% - 280px) !important;
}

.blog-header{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(139,92,246,.04));
  border:1px solid #1a1a2e;border-radius:16px;padding:18px 24px;margin-bottom:20px;
  display:flex;align-items:center;gap:14px;}
.blog-header-icon{width:44px;height:44px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;}
.blog-header-title{font-size:1.1rem;font-weight:700;color:#f1f1f3;}
.blog-header-sub{font-size:.74rem;color:#6b7280;}

.gen-btn button{
    background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;
    border:none!important;border-radius:10px!important;font-weight:600!important;
    font-size:14px!important;padding:12px 24px!important;
    box-shadow:0 4px 16px rgba(99,102,241,.35)!important;
}
.gen-btn button:hover{
    transform:translateY(-1px)!important;
    box-shadow:0 6px 22px rgba(99,102,241,.5)!important;
}

.blog-output{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:14px;
  padding:24px;margin-top:20px;max-height:600px;overflow-y:auto;}
.blog-output h1{color:#f1f1f3;font-size:1.5rem;margin-bottom:16px;}
.blog-output h2{color:#a5b4fc;font-size:1.2rem;margin:20px 0 12px;
  border-bottom:1px solid #1a1a2e;padding-bottom:8px;}
.blog-output h3{color:#c4b5fd;font-size:1rem;margin:16px 0 10px;}
.blog-output p{color:#c4c4d8;line-height:1.7;margin-bottom:12px;}
.blog-output ul, .blog-output ol{margin-left:20px;color:#c4c4d8;}
.blog-output li{margin-bottom:6px;}
.blog-output code{background:#1a1a2e;padding:2px 6px;border-radius:4px;
  color:#86efac;font-family:'JetBrains Mono',monospace;}
.blog-output pre{background:#111128;padding:14px;border-radius:10px;overflow-x:auto;}
.blog-output pre code{background:transparent;padding:0;}
.blog-output img{border-radius:8px;max-width:100%;margin:12px 0;}
.blog-output blockquote{border-left:3px solid #eab308;padding-left:12px;
  color:#eab308;margin:12px 0;}
.blog-output hr{border:0;height:1px;background:linear-gradient(90deg,transparent,#1a1a2e,transparent);margin:20px 0;}
.blog-output a{color:#a5b4fc;text-decoration:none;}
.blog-output a:hover{color:#6366f1;text-decoration:underline;}

.brand-wrap{padding:20px 4px 16px;border-bottom:1px solid #1a1a2e;margin-bottom:16px;}
.brand-row{display:flex;align-items:center;gap:10px;margin-bottom:4px;}
.brand-icon{width:36px;height:36px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;}
.brand-name{font-size:16px;font-weight:700;color:#f1f1f3!important;}
.brand-tagline{font-size:10px;color:#454560!important;margin-left:46px;}

.sec-label{font-size:9.5px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;
  color:#454560!important;margin:16px 2px 8px;display:flex;align-items:center;gap:6px;}
.sec-label::after{content:'';flex:1;height:1px;background:#1a1a2e;}

.img-status-ok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);
  border-radius:8px;padding:8px 12px;font-size:12px;color:#4ade80;margin-bottom:8px;}
.img-status-warn{background:rgba(234,179,8,.1);border:1px solid rgba(234,179,8,.3);
  border-radius:8px;padding:8px 12px;font-size:12px;color:#fbbf24;margin-bottom:8px;}
.img-status-err{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
  border-radius:8px;padding:8px 12px;font-size:12px;color:#f87171;margin-bottom:8px;}
.img-status-info{background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.3);
  border-radius:8px;padding:8px 12px;font-size:12px;color:#a5b4fc;margin-bottom:8px;}

/* Image placeholder styling */
.img-placeholder{background:rgba(99,102,241,.05);border:1.5px dashed rgba(99,102,241,.25);
  border-radius:12px;padding:20px;text-align:center;margin:16px 0;}
.img-placeholder-icon{font-size:32px;margin-bottom:8px;}
.img-placeholder-title{font-weight:600;color:#a5b4fc;font-size:13px;margin-bottom:4px;}
.img-placeholder-desc{font-size:11px;color:#6b7280;}

/* TOC styling */
.toc-item{display:block;padding:4px 0;color:#9696b0;font-size:13px;text-decoration:none;}
.toc-item:hover{color:#a5b4fc;}
.toc-number{color:#6366f1;font-weight:600;margin-right:8px;}
</style>
""",
    unsafe_allow_html=True,
)

# -- Heavy import --
from lang_rag_backend import generate_blog, _GROQ_KEYS

# -- Status checks (DEFINED BEFORE SIDEBAR USE) --
_has_hf_token = bool(os.environ.get("HF_TOKEN"))
_has_google_key = bool(os.environ.get("GOOGLE_API_KEY"))

# -- Sidebar --
with st.sidebar:
    st.markdown(
        """
    <div class="brand-wrap">
      <div class="brand-row">
        <div class="brand-icon">📝</div>
        <div><div class="brand-name">Blog Gen</div></div>
      </div>
      <div class="brand-tagline">AI · Research · Images</div>
    </div>""",
        unsafe_allow_html=True,
    )

    st.page_link("app.py", label="📊  Back to Dashboard")
    st.page_link("pages/1_Chat.py", label="💬  Open Chatbot")
    st.markdown("<div style='margin:6px 0'></div>", unsafe_allow_html=True)

    st.markdown('<div class="sec-label">⚡ Status</div>', unsafe_allow_html=True)

    # Dynamic status colors based on configuration
    hf_dot_color = "#22c55e" if _has_hf_token else "#eab308"
    hf_status = "✅ Active" if _has_hf_token else "⚠️ Needs HF_TOKEN"

    poll_status = "✅ Available (free)"
    poll_dot = "#22c55e"

    google_status = "✅ Active" if _has_google_key else "⚠️ Needs GOOGLE_API_KEY"
    google_dot = "#22c55e" if _has_google_key else "#eab308"

    st.markdown(
        f"""
    <div style="background:#0d0d1a;border:1px solid #1a1a2e;border-radius:12px;
      padding:11px 14px;margin-bottom:14px;">
      <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;">
        <span style="width:7px;height:7px;border-radius:50%;background:#22c55e;
          box-shadow:0 0 6px rgba(34,197,94,.7);display:inline-block"></span>
        <span style="color:#c4c4d8!important;"><b>{len(_GROQ_KEYS)}</b> Groq key(s) loaded</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;">
        <span style="width:7px;height:7px;border-radius:50%;background:#22c55e;
          box-shadow:0 0 6px rgba(34,197,94,.7);display:inline-block"></span>
        <span style="color:#c4c4d8!important;">Blog LLM — <b>ready</b></span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;">
        <span style="width:7px;height:7px;border-radius:50%;background:{hf_dot_color};
          box-shadow:0 0 6px rgba(34,197,94,.7);display:inline-block"></span>
        <span style="color:#c4c4d8!important;">🥇 HF FLUX.1 — <b>Primary</b> ({hf_status})</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;">
        <span style="width:7px;height:7px;border-radius:50%;background:{poll_dot};
          box-shadow:0 0 6px rgba(34,197,94,.7);display:inline-block"></span>
        <span style="color:#c4c4d8!important;">🥈 Pollinations AI — <b>Fallback 1</b> ({poll_status})</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;">
        <span style="width:7px;height:7px;border-radius:50%;background:{google_dot};
          box-shadow:0 0 6px rgba(34,197,94,.7);display:inline-block"></span>
        <span style="color:#c4c4d8!important;">🥉 Google Imagen — <b>Fallback 2</b> ({google_status})</span>
      </div>
    </div>""",
        unsafe_allow_html=True,
    )

    if _has_hf_token:
        st.markdown(
            '<div style="font-size:10.5px;color:#4ade80;padding:8px;'
            "background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.25);"
            'border-radius:8px;line-height:1.6">'
            "✅ <b>Hugging Face FLUX.1</b> — Primary image provider<br>"
            "🥇 Best quality | 🥈 Pollinations AI fallback (free, no key)<br>"
            "🥉 Google Imagen fallback (needs GOOGLE_API_KEY)<br>"
            '<span style="color:#6b7280">If HF credits depleted, auto-falls back to free providers</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="font-size:10.5px;color:#fbbf24;padding:8px;'
            "background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.25);"
            'border-radius:8px;line-height:1.6">'
            "⚠️ No HF_TOKEN — using Pollinations AI (free, no signup)<br>"
            "🥈 Pollinations: completely free, no rate limits<br>"
            '<span style="color:#6b7280">Get HF token at </span>'
            '<a href="https://huggingface.co/settings/tokens" style="color:#a5b4fc">Hugging Face</a>'
            '<span style="color:#6b7280"> for best quality FLUX images</span></div>',
            unsafe_allow_html=True,
        )


# -- Main Area --
st.markdown(
    """
<div class="blog-header">
  <div class="blog-header-icon">📝</div>
  <div>
    <div class="blog-header-title">AI Blog Generator</div>
    <div class="blog-header-sub">Research → Write → Illustrate — powered by Groq + FLUX</div>
  </div>
</div>""",
    unsafe_allow_html=True,
)

st.markdown('<div class="sec-label">🎯 Topic</div>', unsafe_allow_html=True)

topic = st.text_area(
    "Enter a topic for your blog post",
    placeholder="e.g., 'Latest AI trends in 2026', 'India's Got Talent season recap', 'How to build a RAG system'...",
    height=100,
    key="blog_topic_widget",
    label_visibility="collapsed",
)

col1, col2 = st.columns([1, 5])
with col1:
    st.markdown('<div class="gen-btn">', unsafe_allow_html=True)
    generate_clicked = st.button("✨ Generate Blog", key="generate_blog_btn")
    st.markdown("</div>", unsafe_allow_html=True)

# -- Generation --
if generate_clicked and topic.strip():
    with st.spinner(
        "🧠 Researching and writing your blog... (images: HF FLUX.1 → Pollinations → Google Imagen)"
    ):
        try:
            blog_md = generate_blog(topic=topic.strip())
            st.session_state["last_blog"] = blog_md
            st.session_state["last_blog_topic"] = topic.strip()
            st.toast("✅ Blog generated successfully!", icon="📝")
        except Exception as e:
            st.error(f"❌ Blog generation failed: {e}")
            import traceback

            with st.expander("Debug traceback"):
                st.code(traceback.format_exc())

elif generate_clicked and not topic.strip():
    st.warning("Please enter a topic first.")

# -- Display --
if "last_blog" in st.session_state and st.session_state["last_blog"]:
    st.markdown('<div class="sec-label">📄 Preview</div>', unsafe_allow_html=True)

    blog_content = st.session_state["last_blog"]
    has_images = (
        "<img src='data:image/" in blog_content
        or '<img src="data:image/' in blog_content
        or "data:image/png;base64," in blog_content
        or "data:image/jpeg;base64," in blog_content
    )
    has_html_placeholder = (
        "Image generation failed" in blog_content or "img-placeholder" in blog_content
    )
    has_errors = (
        "[IMAGE GENERATION FAILED]" in blog_content
        or "Image generation failed" in blog_content
    )

    if has_images and not has_errors:
        st.markdown(
            '<div class="img-status-ok">🖼️ Images generated and embedded successfully</div>',
            unsafe_allow_html=True,
        )
    elif has_html_placeholder:
        st.markdown(
            '<div class="img-status-warn">⚠️ Some image placeholders shown — images could not be generated for some sections. '
            "Blog text is complete. Check HF_TOKEN or free Pollinations fallback will be used automatically.</div>",
            unsafe_allow_html=True,
        )
    elif has_errors:
        st.markdown(
            '<div class="img-status-warn">⚠️ Some images failed. Blog text is complete.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="img-status-info">📝 Text-only blog — image generation was skipped or produced no output.</div>',
            unsafe_allow_html=True,
        )

    # -- Export Format Selection --
    export_col1, export_col2 = st.columns(2)

    with export_col1:
        st.download_button(
            label="⬇️ Download Markdown",
            data=blog_content,
            file_name=f"{st.session_state.get('last_blog_topic', 'blog').replace(' ', '_').lower()[:50]}.md",
            mime="text/markdown",
            key="download_blog_md",
        )

    with export_col2:
        # Generate PDF (lazy import — only loads when button is used)
        _has_reportlab = False
        try:
            import reportlab

            _has_reportlab = True
        except ImportError:
            pass

        if _has_reportlab:
            if st.button("📄 Generate PDF", key="gen_pdf_btn"):
                with st.spinner("Generating PDF..."):
                    try:
                        import io
                        import re
                        import base64
                        import tempfile
                        import os
                        from reportlab.lib.pagesizes import letter
                        from reportlab.platypus import (
                            SimpleDocTemplate,
                            Paragraph,
                            Spacer,
                            Image as RLImage,
                        )
                        from reportlab.lib.styles import (
                            ParagraphStyle,
                            getSampleStyleSheet,
                        )
                        from reportlab.lib.units import inch
                        from reportlab.lib.enums import TA_CENTER

                        buffer = io.BytesIO()
                        doc = SimpleDocTemplate(
                            buffer,
                            pagesize=letter,
                            rightMargin=72,
                            leftMargin=72,
                            topMargin=72,
                            bottomMargin=18,
                        )

                        styles = getSampleStyleSheet()
                        title_style = ParagraphStyle(
                            "CustomTitle",
                            parent=styles["Heading1"],
                            fontSize=24,
                            spaceAfter=30,
                            textColor="#1a1a2e",
                            alignment=TA_CENTER,
                        )
                        heading_style = ParagraphStyle(
                            "CustomHeading",
                            parent=styles["Heading2"],
                            fontSize=16,
                            spaceAfter=12,
                            spaceBefore=12,
                            textColor="#6366f1",
                        )
                        body_style = ParagraphStyle(
                            "CustomBody",
                            parent=styles["BodyText"],
                            fontSize=11,
                            leading=16,
                            spaceAfter=10,
                        )

                        story = []
                        topic_name = st.session_state.get(
                            "last_blog_topic", "Blog Post"
                        )
                        story.append(Paragraph(topic_name, title_style))
                        story.append(Spacer(1, 0.2 * inch))

                        lines = blog_content.split("\n")
                        for line in lines:
                            line = line.strip()
                            if not line:
                                story.append(Spacer(1, 0.1 * inch))
                                continue
                            # Extract and embed base64 images
                            if "data:image" in line:
                                match = re.search(
                                    r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)", line
                                )
                                if match:
                                    ext, b64data = match.groups()
                                    img_bytes = base64.b64decode(b64data)
                                    tmp_fd, tmp_path = tempfile.mkstemp(
                                        suffix=f".{ext if ext != 'jpeg' else 'jpg'}"
                                    )
                                    with os.fdopen(tmp_fd, "wb") as imgf:
                                        imgf.write(img_bytes)
                                    img = RLImage(
                                        tmp_path, width=5 * inch, height=3.5 * inch
                                    )
                                    story.append(img)
                                    story.append(Spacer(1, 0.1 * inch))
                                else:
                                    story.append(Paragraph("[Image]", body_style))
                                continue
                            if line.startswith("# "):
                                story.append(Paragraph(line[2:], title_style))
                            elif line.startswith("## "):
                                story.append(Paragraph(line[3:], heading_style))
                            elif line.startswith("### "):
                                story.append(Paragraph(line[4:], heading_style))
                            elif line.startswith("- ") or line.startswith("* "):
                                story.append(Paragraph(f"• {line[2:]}", body_style))
                            elif re.match(r"^\d+\. ", line):
                                story.append(Paragraph(line, body_style))
                            else:
                                line = re.sub(
                                    r"\[(.*?)\]\((.*?)\)",
                                    r'<a href="\2" color="blue">\1</a>',
                                    line,
                                )
                                line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)
                                line = re.sub(r"\*(.*?)\*", r"<i>\1</i>", line)
                                story.append(Paragraph(line, body_style))

                        doc.build(story)
                        pdf_bytes = buffer.getvalue()
                        buffer.close()

                        st.download_button(
                            label="⬇️ Download PDF",
                            data=pdf_bytes,
                            file_name=f"{topic_name.replace(' ', '_').lower()[:50]}.pdf",
                            mime="application/pdf",
                            key="download_blog_pdf",
                        )
                    except Exception as e:
                        st.error(f"PDF generation failed: {e}")
        else:
            st.info("📄 PDF export: `pip install reportlab`", icon="ℹ️")

    # -- Render Blog Content --
    # it strips/truncates them. We extract images and use st.image() instead.
    import re
    import base64

    st.markdown('<div class="blog-output">', unsafe_allow_html=True)

    # Split content by image tags (both single and double quoted)
    parts = re.split(r"(<img[^>]+>)", blog_content)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Check if this part is an image tag with base64 data
        img_match = re.search(
            r'<img\s+src=["\']data:image/(\w+);base64,([A-Za-z0-9+/=]+)["\']',
            part,
        )
        if img_match:
            # Extract and render image with st.image() — the only reliable way
            img_format, img_b64 = img_match.groups()
            try:
                img_bytes = base64.b64decode(img_b64)
                st.image(img_bytes, use_container_width=True)
            except Exception as e:
                st.markdown(
                    f'<p style="color:#f87171;font-size:12px;">⚠️ Could not render image: {e}</p>',
                    unsafe_allow_html=True,
                )
        else:
            # Render markdown text
            if part != "</div>":
                st.markdown(part, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
