import re
import json
import io
import html  # ✅ ADDED THIS IMPORT
from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)

# ================= CONFIG =================
# ⚠️ REPLACE THIS WITH YOUR NEW BOT TOKEN
TOKEN = "8504077724:AAGp5Avfvc6Nrq5_4W-xohG0PP0MpsVkmCQ"

# ================= SESSION ================= 
user_sessions = {}

def reset_session(uid):
    user_sessions[uid] = {
        "step": "TITLE",
        "quiz_title": None,
        "quiz_id": None,
        "correct_score": None,
        "negative_score": None,
        "sections": [],          # ✅ REQUIRED for sectional time
        "raw_text": "",
        "mode": None,
        "section_type": None,
        "manual_sections": None,
        "qualifying_sections": []
    }



# ================= RECONSTRUCTION REGEX (COPIED EXACTLY) =================
OPTION_D_END = re.compile(r'^\s*(?:\(?d\)?[\.)])\s*')
NEW_QUESTION_START = re.compile(r'^\s*Q\.\s*\d+', re.I)
HI_MARK = '"Hi":'

# ================= MCQ SPLITTER (COPIED EXACTLY) =================
def split_mcqs(text):
    lines = text.splitlines()
    mcqs = []
    current = []

    q_start = re.compile(r'^\s*Q\.\s*\d+', re.I)

    for line in lines:
        if q_start.match(line.strip()):
            if current:
                mcqs.append("\n".join(current).strip())
                current = []
        current.append(line)

    if current:
        mcqs.append("\n".join(current).strip())

    return [m for m in mcqs if m.strip()]

# ================= HTML ESCAPE (COPIED EXACTLY) =================
def esc(txt):
    return (
        txt.replace("&", "&amp;")
           .replace("<", "&lt;")
           .replace(">", "&gt;")
           .replace("&lt;br&gt;", "<br>")
    )



def parse_mcq(mcq, idx, session):
    lines = mcq.splitlines()

    q_en = []
    q_hi = []
    opts = {}
    answer = None
    sol_en = []
    sol_hi = []

    q_start = re.compile(r'^\s*Q\.\s*\d+', re.I)
    qnum_clean = re.compile(r'^\s*Q\.\s*\d+\s*', re.I)

    opt_pat = re.compile(r'^\s*(?:\(([a-d])\)|([a-d])\))\s*(.*)')
    ans_pat = re.compile(r'Answer:\s*\(?([a-d])\)?')
    exp_pat = re.compile(r'^\s*Explanation\s*:\s*(.*)', re.I)

    current_option = None
    in_explanation = False
    current_lang = "en"

    for line in lines:
        raw = line.rstrip()
        stripped = raw.strip()

        # Language switch
        if stripped.startswith(HI_MARK):
            current_lang = "hi"
            content = stripped.replace(HI_MARK, "").strip()
            if content:
                if current_option:
                    opts[current_option]["hi"] += ("<br>" if opts[current_option]["hi"] else "") + content
                elif in_explanation:
                    sol_hi.append(content)
                else:
                    q_hi.append(content)
            continue

        # Question number line
        if q_start.match(stripped):
            q_en.append(qnum_clean.sub("", raw))
            continue

        # Answer
        m_ans = ans_pat.match(stripped)
        if m_ans:
            answer = m_ans.group(1).lower()
            current_option = None
            in_explanation = False
            current_lang = "en"
            continue

        # Explanation start
        m_exp = exp_pat.match(stripped)
        if m_exp:
            in_explanation = True
            current_lang = "en"
            sol_en.append(m_exp.group(1))
            current_option = None
            continue

        # Explanation continuation
        if in_explanation:
            if stripped:
                (sol_hi if current_lang == "hi" else sol_en).append(stripped)
            continue

        # Option start
        m_opt = opt_pat.match(stripped)
        if m_opt:
            key = (m_opt.group(1) or m_opt.group(2)).lower()
            current_option = key
            current_lang = "en"
            opts[key] = {"en": m_opt.group(3).strip(), "hi": ""}
            continue

        # Option multiline
        if current_option and stripped:
            opts[current_option][current_lang] += "<br>" + stripped
            continue

        # Question text
        (q_hi if current_lang == "hi" else q_en).append(raw)

    if len(opts) != 4 or answer not in opts:
        raise ValueError("Invalid MCQ format")

    return {
        "answer": str("abcd".index(answer) + 1),
        "correct_score": session["correct_score"],
        "deleted": "0",
        "difficulty_level": "0",
        "id": str(50000 + idx),
        "negative_score": session["negative_score"],

        "option_1": {"en": esc(opts["a"]["en"]), "hi": esc(opts["a"]["hi"])},
        "option_2": {"en": esc(opts["b"]["en"]), "hi": esc(opts["b"]["hi"])},
        "option_3": {"en": esc(opts["c"]["en"]), "hi": esc(opts["c"]["hi"])},
        "option_4": {"en": esc(opts["d"]["en"]), "hi": esc(opts["d"]["hi"])},

        "option_5": "",
        "option_image_1": "",
        "option_image_2": "",
        "option_image_3": "",
        "option_image_4": "",
        "option_image_5": "",

        "question": {
            "en": esc("<br>".join(q_en)),
            "hi": esc("<br>".join(q_hi))
        },
        "question_image": "",
        "quiz_id": session["quiz_id"],

        "solution_heading": "",
        "solution_image": "",
        "solution_text": {
            "en": esc("<br>".join(sol_en)),
            "hi": esc("<br>".join(sol_hi))
        },
        "solution_video": "",
        "sortingparam": "0.00"
    }


# ================= COMMANDS =================
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("Use Default Sections", callback_data="sec_default")],
        [InlineKeyboardButton("Give Manually", callback_data="sec_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚀 Starting new JSON generation.\n\nSelect section mode:",
        reply_markup=reply_markup
    )

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(update.effective_user.id)
    await update.message.reply_text("🔄 Session reset. Send /quiz to start again.")

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    session = user_sessions.get(uid)
    if not session:
        return

    await query.answer()

    if query.data == "sec_default":
        session["section_type"] = "default"
        keyboard = [
            [InlineKeyboardButton("MTS", callback_data="def_mts")],
            [InlineKeyboardButton("CPO", callback_data="def_cpo")]
        ]
        await query.edit_message_text(
            "Select default test type:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "sec_manual":
        session["section_type"] = "manual"
        session["step"] = "MANUAL_SEC_INPUT"
        await query.edit_message_text(
            "Please provide sections in this format:\n"
            "1. SECTION NAME(START-END)-time(min)\n\n"
            "Example:\n"
            "1. REASONING(1-25)-25\n"
            "2. GK GS(26-50)-20"
        )

    elif query.data == "def_mts":
        session["sections"] = [
            {"name": "MATH AND REASONING", "start": 1, "end": 40, "time": 45},
            {"name": "ENGLISH AND GK", "start": 41, "end": 90, "time": 45}
        ]
        session["qualifying_sections"] = ["MATH AND REASONING"]
        session["step"] = "TITLE"
        await query.edit_message_text(
            "✅ Sections Selected:\n"
            "1. MATH AND REASONING(1-40)-45\n"
            "2. ENGLISH AND GK(41-90)-45\n\n"
            "Now send the **Quiz Title**."
        )

    elif query.data == "def_cpo":
        session["sections"] = [
            {"name": "REASONING", "start": 1, "end": 50, "time": 30},
            {"name": "GENERAL AWARENESS", "start": 51, "end": 100, "time": 30},
            {"name": "MATH", "start": 101, "end": 150, "time": 30},
            {"name": "ENGLISH", "start": 151, "end": 200, "time": 30}
        ]
        session["step"] = "TITLE"
        await query.edit_message_text(
            "✅ Sections Selected:\n"
            "1. REASONING(1-50)-30\n"
            "2. GENERAL AWARENESS(51-100)-30\n"
            "3. MATH(101-150)-30\n"
            "4. ENGLISH(151-200)-30\n\n"
            "Now send the **Quiz Title**."
        )

# ================= TEXT HANDLER =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session:
        return

    text = update.message.text.strip()

    # New Step: Manual Section Input (WITH TIME)
    if session["step"] == "MANUAL_SEC_INPUT":
        session["manual_sections"] = text
        session["sections"] = []

        sec_pattern = re.compile(r'\d+\.\s*(.+?)\((\d+)-(\d+)\)-(\d+)')
        
       for line in text.splitlines():
            m = sec_pattern.search(line)
            if m:
                sec_name = m.group(1).strip()

                # Detect qualifying section using -Q suffix
                if sec_name.endswith("-Q"):
                    clean_name = sec_name[:-2].strip()
                    session["qualifying_sections"].append(clean_name)
                    sec_name = clean_name

                session["sections"].append({
                    "name": sec_name,
                    "start": int(m.group(2)),
                    "end": int(m.group(3)),
                    "time": int(m.group(4))
                })
        

        session["step"] = "TITLE"
        await update.message.reply_text("✅ Sections Saved.\n\nPlease send the **Quiz Title**.")
        return


    # Step 1: Quiz Title
    if session["step"] == "TITLE":
        session["quiz_title"] = text
        session["step"] = "ID"
        await update.message.reply_text(f"✅ Title: {text}\n\nNow send the **Quiz ID** (e.g. GKTest).")
        return

    # Step 2: Quiz ID
    if session["step"] == "ID":
        # Remove spaces to ensure valid filename/ID
        clean_id = text.replace(" ", "")
        session["quiz_id"] = clean_id
        session["step"] = "CORRECT"
        await update.message.reply_text(f"✅ ID: {clean_id}\n\nSend **Correct Answer Score** (e.g. 2).")
        return

    # Step 3: Correct Score
    if session["step"] == "CORRECT":
        session["correct_score"] = text
        session["step"] = "NEGATIVE"
        await update.message.reply_text("Send **Negative Score** (e.g. 0.5 or 0).")
        return

    
    # Step 4: Negative Score
    if session["step"] == "NEGATIVE":
        session["negative_score"] = text
        session["step"] = "MCQS"
        await update.message.reply_text(
            "Now send MCQs (copy-paste text OR upload .txt file).\n\nSend /done when finished."
        )
        return


    # Step 6: Collect MCQs
    if session["step"] == "MCQS":
        if session["mode"] not in (None, "text"):
            await update.message.reply_text("Only one input type allowed.")
            return

        session["mode"] = "text"
        if not session["raw_text"]:
            session["raw_text"] = text
            return

        prev_last = session["raw_text"].splitlines()[-1].strip()
        if OPTION_D_END.match(prev_last) and NEW_QUESTION_START.match(text):
            session["raw_text"] += "\n\n" + text
        else:
            session["raw_text"] += "\n" + text

# ================= FILE HANDLER =================
async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or session["step"] != "MCQS":
        return

    if session["mode"] not in (None, "file"):
        await update.message.reply_text("Only one input type allowed.")
        return

    session["mode"] = "file"
    doc: Document = update.message.document

    file = await doc.get_file()
    content = (await file.download_as_bytearray()).decode("utf-8")

    session["raw_text"] += "\n" + content
    await update.message.reply_text("📄 File received. You can send more files or /done.")


# ================= DONE COMMAND =================
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)

    if not session or session["step"] != "MCQS":
        await update.message.reply_text("You haven't started a quiz yet.")
        return

    # 1. Parse Questions
    mcqs = split_mcqs(session["raw_text"])
    question_objects = []

    for i, m in enumerate(mcqs, start=1):
        try:
            obj = parse_mcq(m, i, session)
            question_objects.append(obj)
        except Exception as e:
            await update.message.reply_text(f"❌ Error in Question {i}: {str(e)}")
            return

    # 2. Process Sections (UPDATED – REQUIRED)
    sections_json = {}
    total_time_min = 0

    for sec in session["sections"]:
        start_q = sec["start"]
        end_q = sec["end"]
        sec_name = sec["name"]
        sec_time = sec["time"]

        sections_json[sec_name] = {
            "time_seconds": sec_time * 60,
            "questions": question_objects[start_q - 1:end_q]
        }
        total_time_min += sec_time

    # 3. Build Final JSON Structure (UPDATED – REQUIRED)
    final_data = {
        "meta": {
            "title": session["quiz_title"],
            "id": session["quiz_id"],
            "total_questions": len(question_objects),
            "correct_score": session["correct_score"],
            "negative_score": session["negative_score"],
            "timer_minutes": str(total_time_min),
            "timer_seconds": total_time_min * 60,
            "qualifying_sections": session["qualifying_sections"]
        },
        "sections": sections_json
    }

    # 5. Generate File
    json_str = json.dumps(final_data, indent=2, ensure_ascii=False)
    file_name = f"{session['quiz_id']}.json"

    # 6. Create Caption (UPDATED – REQUIRED)
    caption = (
        f"✅ <b>JSON Generated Successfully!</b>\n\n"
        f"📌 <b>Quiz Title:</b> {session['quiz_title']}\n"
        f"🆔 <b>Quiz ID:</b> {session['quiz_id']}\n"
        f"📊 <b>Total Questions:</b> {len(question_objects)}\n"
        f"⏱️ <b>Total Time:</b> {total_time_min} mins\n"
        f"➕ <b>Positive Mark:</b> {session['correct_score']}\n"
        f"➖ <b>Negative Mark:</b> {session['negative_score']}\n"
    )

    await update.message.reply_document(
        document=io.BytesIO(json_str.encode("utf-8")),
        filename=file_name,
        caption=caption,
        parse_mode="HTML"
    )
    # Calculate Total Marks
    total_qs = len(question_objects)
    total_marks = total_qs * int(session["correct_score"])

    # Updated Format
    website_code = (
        f'{{"id": "{session["quiz_id"]}", '
        f'"title": "{session["quiz_title"]}", '
        f'"type": "paid", '
        f'"releaseDate": "", '
        f'"qs": {total_qs}, '
        f'"time": "{total_time_min} Min", '
        f'"marks": {total_marks}}}'
    )
   

    # ✅ ESCAPE THE HTML CODE SO TELEGRAM SENDS IT AS TEXT
    escaped_code = html.escape(website_code)

    # 8. Send the Snippet Message
    await update.message.reply_text(
        f"📋 <b>Website Code Snippet:</b>\n\n"
        f"<pre><code class='language-html'>{escaped_code}</code></pre>",
        parse_mode="HTML"
    )

    reset_session(uid)


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Document.TEXT | filters.Document.MimeType("text/plain"), file_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
