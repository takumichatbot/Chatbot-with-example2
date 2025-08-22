import os
import json
from flask import Flask, render_template, request, jsonify, abort
from dotenv import load_dotenv
import google.generativeai as genai
from langdetect import detect, LangDetectException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import re
# ▼▼▼ 翻訳ライブラリをインポート ▼▼▼
from google.cloud import translate_v2 as translate

load_dotenv()

# --- 設定 ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

# --- LINE APIの初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
line_bot_api = None
handler = None
if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)
# ▼▼▼ 翻訳クライアントを初期化 ▼▼▼
translate_client = translate.Client()

# --- 多言語ナレッジベースとプロンプトの読み込み ---
def load_json_files(directory):
    data = {}
    for filename in os.listdir(directory):
        if filename.endswith('.json'):
            lang = filename.split('.')[0]
            with open(os.path.join(directory, filename), 'r', encoding='utf-8') as f:
                data[lang] = json.load(f)
    return data

knowledge_bases = load_json_files('static/knowledge')
# (prompts辞書は変更なし)

# --- 言語判定関数 ---
def detect_language(text):
    try:
        return detect(text)
    except LangDetectException:
        return 'ja'

# --- Gemini応答生成関数 (自動翻訳機能付き) ---
def get_gemini_answer(question, lang):
    print(f"質問: {question} (言語: {lang})")
    
    base_lang = 'ja' # システムの基準言語
    target_lang = lang

    # STEP 0: 未知の言語の場合、質問を基準言語に翻訳
    if target_lang not in knowledge_bases:
        print(f"{target_lang} は未対応言語。質問を {base_lang} に翻訳します。")
        translation = translate_client.translate(question, target_language=base_lang)
        question = translation['translatedText']
        lang = base_lang # これ以降の処理は基準言語で行う

    qa_data = knowledge_bases.get(lang)
    prompt_data = prompts.get(lang)
    qa_prompt_text = "\n\n".join([f"### {key}\n{value}" for key, value in qa_data['data'].items()])
    model = genai.GenerativeModel('models/gemini-1.5-flash')

    # STEP 1: 通常の回答を生成 (基準言語で)
    try:
        full_question = f"{prompt_data['system_role']}\n\n---\n## ルール・規則\n{qa_prompt_text}\n---\n\nお客様の質問: {question}"
        response = model.generate_content(full_question, request_options={'timeout': 30})
        answer = response.text.strip() if response and response.text else prompt_data['not_found']
    except Exception as e:
        print(f"Gemini APIエラー (回答生成): {e}")
        answer = prompt_data['error']
        # エラーでも後続処理に進む
        follow_up_questions = []

    # STEP 2: 関連質問を生成 (基準言語で)
    # エラー時は関連質問を生成しない
    if "申し訳ありません" not in answer:
        try:
            follow_up_request = f"ユーザーの質問: {question}\nAIの回答: {answer}\n\n{prompt_data['follow_up_prompt']}"
            follow_up_response = model.generate_content(follow_up_request, request_options={'timeout': 20})
            json_str_match = re.search(r'\[.*\]', follow_up_response.text, re.DOTALL)
            follow_up_questions = json.loads(json_str_match.group()) if json_str_match else []
        except Exception as e:
            print(f"Gemini APIエラー (関連質問生成): {e}")
            follow_up_questions = []
    else:
        follow_up_questions = []

    # STEP 3: 未知の言語の場合、回答と関連質問を元の言語に翻訳
    if target_lang not in knowledge_bases:
        print(f"回答と関連質問を {target_lang} に翻訳します。")
        # 回答の翻訳
        answer_translation = translate_client.translate(answer, target_language=target_lang)
        answer = answer_translation['translatedText']
        # 関連質問の翻訳 (リストを一括で翻訳)
        if follow_up_questions:
            questions_translations = translate_client.translate(follow_up_questions, target_language=target_lang)
            follow_up_questions = [item['translatedText'] for item in questions_translations]

    return {"answer": answer, "follow_up_questions": follow_up_questions}

# (Flaskルーティング部分は変更なし)
@app.route('/')
def index():
    example_questions = knowledge_bases['ja'].get('example_questions', [])
    return render_template('index.html', example_questions=example_questions)

@app.route('/ask', methods=['POST'])
def ask_chatbot():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({'answer': '質問が空です。', "follow_up_questions": []})
    lang = detect_language(user_message)
    bot_response_data = get_gemini_answer(user_message, lang)
    return jsonify(bot_response_data)

# (LINE関連のコードも変更なし)
# ...

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port, debug=False)