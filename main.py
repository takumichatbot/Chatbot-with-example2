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
prompts = {
    'ja': {
        "system_role": "あなたはLARUbotのカスタマーサポートAIです。以下の「ルール・規則」セクションに記載されている情報のみに基づいて、お客様からの質問に絵文字を使わずに丁寧に回答してください。**記載されていない質問には「申し訳ありませんが、その情報はこのQ&Aには含まれていません。」と答えてください。**お客様がスムーズに手続きを進められるよう、元気で丁寧な言葉遣いで案内してください。",
        "follow_up_prompt": "上記のユーザーからの質問とAIの回答に基づき、ユーザーが次に関心を持ちそうな関連性の高い質問を3つ提案してください。簡潔で分かりやすい質問にしてください。回答は必ずJSON形式の文字列リスト（例: [\"質問1\", \"質問2\", \"質問3\"]）で、リスト以外の文字列は一切含めずに返してください。適切な質問がなければ空のリスト `[]` を返してください。",
        "not_found": "申し訳ありませんが、その情報はこのQ&Aには含まれていません。",
        "error": "申し訳ありませんが、現在AIが応答できません。しばらくしてから再度お試しください。"
    },
    'en': {
        "system_role": "You are a customer support AI for LARUbot. Based only on the information provided in the 'Rules & Regulations' section below, please answer customer questions politely and without using emojis. **If a question is not covered, reply with 'I'm sorry, but that information is not included in this Q&A.'** Please use a cheerful and polite tone to guide customers smoothly.",
        "follow_up_prompt": "Based on the user's question and the AI's answer above, suggest three relevant follow-up questions the user might be interested in next. Keep the questions concise and clear. Your response must be only a JSON formatted list of strings (e.g., [\"Question 1\", \"Question 2\", \"Question 3\"]) with no other text. If no suitable questions can be generated, return an empty list `[]`.",
        "not_found": "I'm sorry, but that information is not included in this Q&A.",
        "error": "Sorry, the AI is currently unable to respond. Please try again later."
    }
}

# --- 言語判定関数 ---
def detect_language(text):
    try:
        lang = detect(text)
        # サポートしている言語(ja, en)以外は 'ja' にする
        return lang if lang in knowledge_bases else 'ja'
    except LangDetectException:
        return 'ja' 

# --- Gemini応答生成関数 ---
def get_gemini_answer(question, lang):
    print(f"質問: {question} (言語: {lang})")
    
    qa_data = knowledge_bases.get(lang, knowledge_bases['ja'])
    prompt_data = prompts.get(lang, prompts['ja'])
    
    qa_prompt_text = "\n\n".join([f"### {key}\n{value}" for key, value in qa_data['data'].items()])
    model = genai.GenerativeModel('models/gemini-1.5-flash')

    # STEP 1: 通常の回答を生成
    try:
        full_question = f"""{prompt_data['system_role']}

---
## ルール・規則 (Rules & Regulations)
{qa_prompt_text}
---

お客様の質問 (Customer's Question): {question}
"""
        response = model.generate_content(full_question, request_options={'timeout': 30})
        answer = response.text.strip() if response and response.text else prompt_data['not_found']
    except Exception as e:
        print(f"Gemini APIエラー (回答生成): {e}")
        return {"answer": prompt_data['error'], "follow_up_questions": []}

    # STEP 2: 関連質問を生成
    try:
        follow_up_request = f"""ユーザーの質問: {question}
AIの回答: {answer}

{prompt_data['follow_up_prompt']}"""
        follow_up_response = model.generate_content(follow_up_request, request_options={'timeout': 20})
        
        json_str_match = re.search(r'\[.*\]', follow_up_response.text, re.DOTALL)
        if json_str_match:
            follow_up_questions = json