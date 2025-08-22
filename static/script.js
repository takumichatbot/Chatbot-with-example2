let currentLang = 'ja';
let translations = {};
let knowledgeBases = {};

// --- 関数定義 ---

async function setLanguage(lang) {
    if (lang === currentLang && translations[lang]) return;
    try {
        if (!translations[lang] || !knowledgeBases[lang]) {
            const [transRes, knowledgeRes] = await Promise.all([
                fetch(`/static/translations/${lang}.json`),
                fetch(`/static/knowledge/${lang}.json`)
            ]);
            translations[lang] = await transRes.json();
            knowledgeBases[lang] = await knowledgeRes.json();
        }
        updateUI(lang);
    } catch (error) {
        console.error('Failed to load language files:', error);
    }
}

function updateUI(lang) {
    currentLang = lang;
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-i18n-key]').forEach(el => {
        const key = el.getAttribute('data-i18n-key');
        if (translations[lang] && translations[lang][key]) el.textContent = translations[lang][key];
    });
    document.querySelectorAll('[data-i18n-key-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-key-placeholder');
        if (translations[lang] && translations[lang][key]) el.placeholder = translations[lang][key];
    });
    // 起動時の質問例を更新
    const initialExamplesContainer = document.getElementById('initial-example-questions');
    initialExamplesContainer.innerHTML = '';
    if (knowledgeBases[lang] && knowledgeBases[lang].example_questions) {
        knowledgeBases[lang].example_questions.forEach(q => {
            const button = document.createElement('button');
            button.className = 'example-btn';
            button.textContent = q;
            initialExamplesContainer.appendChild(button);
        });
    }
}

// 質問例ボタンを「メッセージとして」表示する関数
function displayFollowUpQuestions(questions) {
    const messagesContainer = document.getElementById('chatbot-messages');
    
    // 既存の動的な質問コンテナがあれば削除
    const oldContainer = document.getElementById('dynamic-example-questions');
    if(oldContainer) oldContainer.remove();

    if (questions && questions.length > 0) {
        const container = document.createElement('div');
        // IDを付与して後から削除できるようにする
        container.id = 'dynamic-example-questions';
        container.className = 'example-questions-container';
        
        questions.forEach(q => {
            const button = document.createElement('button');
            button.className = 'example-btn';
            button.textContent = q;
            container.appendChild(button);
        });
        messagesContainer.appendChild(container);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

async function sendMessage(message = null) {
    const userInput = document.getElementById('user-input');
    const userMessage = message || userInput.value.trim();
    if (userMessage === '') return;
    
    addMessageToChat('user', userMessage);
    userInput.value = '';

    // 初回起動時の質問例コンテナを非表示にする
    const initialContainer = document.getElementById('initial-example-questions');
    if (initialContainer) initialContainer.style.display = 'none';
    
    // 送信時に既存の動的な質問例ボタンをクリア
    displayFollowUpQuestions([]);

    const loadingMessageId = 'loading-' + new Date().getTime();
    addMessageToChat('bot', '...', true, loadingMessageId);

    try {
        const response = await fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: userMessage })
        });
        if (!response.ok) throw new Error(`サーバーエラー: ${response.status}`);
        
        const data = await response.json();
        
        removeLoadingMessage(loadingMessageId);
        addMessageToChat('bot', data.answer);
        displayFollowUpQuestions(data.follow_up_questions);

    } catch (error) {
        console.error('Fetchエラー:', error);
        removeLoadingMessage(loadingMessageId);
        const errorMsg = currentLang === 'en' 
            ? 'Sorry, a network connection issue occurred. Please try again later.'
            : '申し訳ありませんが、ネットワーク接続に問題が発生しました。しばらくしてから再度お試しください。';
        addMessageToChat('bot', errorMsg);
    }
}

function addMessageToChat(sender, message, isLoading = false, id = null) {
    const messagesContainer = document.getElementById('chatbot-messages');
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', `${sender}-message`);
    if (isLoading) {
        messageDiv.classList.add('loading-message');
        if (id) messageDiv.id = id;
    }
    const linkifiedMessage = message.replace(/(https?:\/\/[^\s<>"'()]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #667eea;">$1</a>');
    messageDiv.innerHTML = linkifiedMessage;
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeLoadingMessage(id) {
    const loadingMessageElement = document.getElementById(id);
    if (loadingMessageElement) loadingMessageElement.remove();
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

// --- イベントリスナー設定 ---
document.addEventListener('DOMContentLoaded', () => {
    
    const langSwitcher = document.querySelector('.language-switcher');
    if (langSwitcher) {
        langSwitcher.addEventListener('click', (event) => {
            const button = event.target.closest('[data-lang]');
            if (button) setLanguage(button.getAttribute('data-lang'));
        });
    }

    // BODY全体でイベントを監視する形に変更
    document.body.addEventListener('click', (event) => {
        if (event.target.classList.contains('example-btn')) {
            sendMessage(event.target.textContent);
        }
    });

    const sendButton = document.getElementById('send-button');
    if(sendButton) sendButton.addEventListener('click', () => sendMessage());

    setLanguage('ja');
});