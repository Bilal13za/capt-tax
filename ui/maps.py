"""Chapter Maps — mind maps per chapter + importance tiers.

Pure helpers are importable without streamlit; only ``render()`` touches it.
"""

import html as _html
import sqlite3 as _sqlite3

try:
    import streamlit as st
    import streamlit.components.v1 as _components
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None
    _components = None

from core import studymaps as _sm
from core import mapcards as _mc


# ---------------------------------------------------------------------------
# Mind-map HTML (pure inline CSS, <details> for collapse — no external libs)
# ---------------------------------------------------------------------------

def _tree_html(tree: dict, accent: str, numbered: bool,
               checklist: bool) -> str:
    ch = tree["chapter"]
    parts = [f"""<style>
.mmap{{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
font-size:14px;line-height:1.45;color:#1a1a1a}}
.mmap ul{{list-style:none;margin:0;padding-left:22px;position:relative}}
.mmap>ul{{padding-left:6px}}
.mmap ul ul::before{{content:'';position:absolute;left:8px;top:0;bottom:8px;
border-left:2px solid #d5d8dc}}
.mmap li{{margin:5px 0;position:relative}}
.mmap li::before{{content:'';position:absolute;left:-14px;top:11px;width:12px;
border-top:2px solid #d5d8dc}}
.mmap>ul>li::before{{display:none}}
.mmap summary{{cursor:pointer;font-weight:600;background:#f4f6f7;
border:1px solid #d5d8dc;border-left:5px solid {accent};
border-radius:6px;padding:6px 10px;display:block}}
.mmap summary:hover{{background:#eaf2f8}}
.mmap summary .cnt{{font-weight:400;color:#5d6d7e;font-size:12px}}
.mmap .root{{font-size:17px;font-weight:700;background:{accent};color:#fff;
border-radius:8px;padding:10px 14px;margin-bottom:10px}}
.mmap .leaf{{background:#fff;border:1px solid #e5e8e8;border-radius:5px;
padding:4px 9px;display:block}}
.mmap .pg{{color:#7f8c8d;font-size:11px;white-space:nowrap}}
.mmap .q{{border-left:3px solid #2e86c1}}
.mmap .d{{border-left:3px solid #7d3c98}}
.mmap .tools{{margin:0 0 10px 0}}
.mmap .tools button{{margin-right:8px;padding:4px 12px;border:1px solid #aab7b8;
border-radius:5px;background:#fff;cursor:pointer;font-size:13px}}
</style>"""]
    root_title = _html.escape(
        f"Ch {ch.get('number')} · {ch.get('title', '')}")
    parts.append(f'<div class="mmap"><div class="root">{root_title}</div>')
    parts.append(
        '<div class="tools"><button onclick="document.querySelectorAll('
        "'#mmap details').forEach(d=>d.open=true)\">Expand all</button>"
        '<button onclick="document.querySelectorAll('
        "'#mmap details').forEach((d,i)=>d.open=(i===0))\">Collapse all</button></div>")
    parts.append('<ul id="mmap"><li><ul>')
    for gi, g in enumerate(tree["groups"], 1):
        gname = _html.escape(g["name"])
        prefix = f"{gi}. " if numbered else ("☐ " if checklist else "")
        leaves = []
        for leaf in g["leaves"]:
            label = _html.escape(leaf["label"])
            pg = (f' <span class="pg">p.{leaf["page"]}</span>'
                  if leaf.get("page") else "")
            cls = {"question": "q", "definition": "d"}.get(
                leaf.get("kind"), "")
            detail = _html.escape(leaf.get("detail") or "")
            title_attr = f' title="{detail}"' if detail else ""
            leaves.append(
                f'<li><span class="leaf {cls}"{title_attr}>{label}{pg}</span></li>')
        parts.append(
            f"<li><details open><summary>{prefix}{gname} "
            f'<span class="cnt">({len(leaves)})</span></summary><ul>'
            + "".join(leaves) + "</ul></details></li>")
    parts.append("</ul></li></ul></div>")
    return "".join(parts)


def _chapter_options(conn):
    stats = _sm.chapter_stats(conn)
    tiers = _sm.get_classification(conn)
    rows = []
    for cid, s in stats.items():
        t = tiers.get(cid, {})
        tier = t.get("tier", "foundation")
        info = _sm.TIERS[tier]
        rows.append({
            "id": cid,
            "number": s["number"] or 0,
            "tier": tier,
            "label": (f"{info['stars']} Ch {s['number']} · {s['title']} "
                      f"({s['question_count']} Qs)"),
        })
    rows.sort(key=lambda r: (_sm.TIER_ORDER.index(r["tier"]), r["number"]))
    return rows


# ---------------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------------

def render(conn):
    if st is None:  # pragma: no cover
        return
    st.header("🗺 Chapter Maps")
    st.caption(
        "Mind maps for every chapter, the study format that suits each one, "
        "and topics ranked by importance. Importance tiers are computed from "
        "**this book's own practice-question distribution and chapter sizes** "
        "— they are study guidance, not ICAP's official syllabus weightage.")
    # Ensure classification exists (first run computes it deterministically).
    _sm.get_classification(conn)

    options = _chapter_options(conn)
    if not options:
        st.info("No chapters loaded yet — import a content pack first.")
        return
    labels = [o["label"] for o in options]
    default_ix = 0
    prev = st.session_state.get("maps_chapter")
    if prev in [o["id"] for o in options]:
        default_ix = [o["id"] for o in options].index(prev)
    choice = st.selectbox("Chapter", labels, index=default_ix,
                          key="maps_chapter_select")
    cid = options[labels.index(choice)]["id"]
    st.session_state["maps_chapter"] = cid

    stats = _sm.chapter_stats(conn)[cid]
    tiers = _sm.get_classification(conn)
    trow = tiers[cid]
    tier, info = trow["tier"], _sm.TIERS[trow["tier"]]
    fmt_key, fmt_reason = _sm.best_format(cid)
    fmt = _sm.FORMATS[fmt_key]

    # --- importance panel -------------------------------------------------
    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader(f"{info['stars']} {info['label']}")
        st.write(info["blurb"])
        note = _sm.chapter_note(cid)
        if note:
            st.info(f"📌 {note}")
        if trow.get("is_override"):
            st.caption("✏️ Tier manually adjusted by you (override).")
    with c2:
        st.metric("Practice questions", stats["question_count"])
        st.metric("Pages",
                  f"{stats['page_start']}–{stats['page_end']}")
        st.metric("Tier score", f"{trow['score']:.3f}")
    with st.expander("Why this rating? (the exact formula)"):
        st.write(_sm.FORMULA_TEXT)
        st.write(f"This chapter: {trow['rationale']}.")
        st.write(
            "Question counts come from the 131 practice questions printed in "
            "the textbook itself. A chapter with many practice questions gets "
            "a higher tier because the author's own question selection is the "
            "best available signal of what gets examined.")
        new_tier = st.selectbox(
            "Adjust tier manually",
            ["(auto)"] + [f"{_sm.TIERS[t]['stars']} {_sm.TIERS[t]['label']}"
                          for t in _sm.TIER_ORDER],
            key=f"tier_override_{cid}")
        if new_tier != "(auto)":
            picked = [t for t in _sm.TIER_ORDER
                      if _sm.TIERS[t]["label"] in new_tier][0]
            if st.button("Save override", key=f"save_tier_{cid}"):
                _sm.set_tier_override(conn, cid, picked)
                st.success("Tier updated.")
                st.rerun()

    # --- suggested format + deep links ------------------------------------
    st.subheader(f"{fmt['icon']} Suggested format: {fmt['label']}")
    st.write(fmt_reason)
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("🃏 Open Flashcards", key=f"goto_fc_{cid}"):
            st.session_state["nav"] = "Flashcards"
            st.rerun()
    with b2:
        if st.button("❓ Open Question Bank", key=f"goto_q_{cid}"):
            st.session_state["nav"] = "Question Bank"
            st.rerun()
    with b3:
        if st.button("📖 Open Learn", key=f"goto_learn_{cid}"):
            st.session_state["nav"] = "Learn"
            st.rerun()
    if st.button("🃏 Create flashcards from this map", key=f"mapcards_{cid}"):
        n = _mc.generate_map_cards(conn, cid)
        if n:
            st.success(f"Created {n} map card(s). Review them in "
                       f"Flashcards → Map drill.")
        else:
            st.info("Map cards already exist for this chapter — nothing new "
                    "created.")

    # --- mind map ----------------------------------------------------------
    st.subheader("Chapter mind map")
    st.caption("Click any branch to collapse it. Hover a definition for a "
               "preview. Page numbers jump back to the source.")
    tree = _sm.build_chapter_map(conn, cid)
    n_leaves = sum(len(g["leaves"]) for g in tree["groups"])
    if not tree["groups"]:
        st.info("No mappable content found for this chapter yet.")
    else:
        html_blob = _tree_html(tree, info["color"],
                               numbered=(fmt_key == "flow"),
                               checklist=(fmt_key == "checklist"))
        height = min(300 + 26 * len(tree["groups"]) + 20 * n_leaves, 1400)
        _components.html(html_blob, height=height, scrolling=True)

    # --- topic importance ---------------------------------------------------
    st.subheader("Topics by importance")
    st.caption("Ranked by how much of the chapter each topic group covers "
               "(slide count).")
    groups = _sm.group_importance(conn, cid)
    if not groups:
        st.info("No topic groups found for this chapter.")
    else:
        for g in groups:
            c1, c2 = st.columns([3, 2])
            with c1:
                st.write(f"**{g['name']}**")
            with c2:
                st.progress(min(g["share"], 1.0),
                            text=f"{g['leaves']} slides · {g['share']:.0%}")
