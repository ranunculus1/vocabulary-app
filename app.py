#!/usr/bin/env python3
"""
📚 背单词网站 - 基于 Flask + SQLite
功能：
- 导入自定义词书（CSV/JSON 格式）
- 学习新单词
- 复习已学单词（艾宾浩斯遗忘曲线）
- 显示今日复习数量
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
import sqlite3
import json
import csv
from datetime import datetime, timedelta
import os
import urllib.request
import ssl

app = Flask(__name__)
# Vercel Serverless 环境下使用绝对路径
if os.environ.get('VERCEL'):
    DB_PATH = '/var/task/vocabulary.db'
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), 'vocabulary.db')

# 艾宾浩斯遗忘曲线复习间隔（天）
# 第 1 次：1 天，第 2 次：2 天，第 3 次：4 天，第 4 次：7 天，第 5 次：15 天，第 6 次：30 天，第 7 次：60 天，第 8 次：90 天
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60, 90]

# DeepSeek API 配置（从环境变量读取）
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions'
DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 词书表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 单词表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            meaning TEXT NOT NULL,
            example TEXT,
            FOREIGN KEY (book_id) REFERENCES books (id),
            UNIQUE (book_id, word)
        )
    ''')
    
    # 学习记录表（已认识的单词）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            review_count INTEGER DEFAULT 0,
            next_review_at TIMESTAMP,
            mastered INTEGER DEFAULT 0,
            FOREIGN KEY (word_id) REFERENCES words (id),
            UNIQUE (word_id)
        )
    ''')
    
    # 待重学表（学习时点"不认识"的单词）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS relearn_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL UNIQUE,
            book_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (word_id) REFERENCES words (id)
        )
    ''')
    
    # 多阶段学习进度表（带间隔）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL UNIQUE,
            book_id INTEGER NOT NULL,
            stage INTEGER DEFAULT 0,  -- 0:未开始，1:已初学，2:释义选择通过，3:拼写英文通过，4:拼写中文通过，5:完成
            words_since_stage INTEGER DEFAULT 0,  -- 当前阶段后已学习的单词数（用于间隔计数）
            correct_count INTEGER DEFAULT 0,  -- 正确次数
            wrong_count INTEGER DEFAULT 0,  -- 错误次数
            last_practiced_at TIMESTAMP,
            FOREIGN KEY (word_id) REFERENCES words (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

# ============== 页面路由 ==============

@app.route('/vconsole.min.js')
def serve_vconsole():
    return send_from_directory('.', 'vconsole.min.js')

@app.route('/')
def index():
    """首页"""
    return render_template('index.html')

@app.route('/books')
def books():
    """词书列表"""
    return render_template('books.html')

@app.route('/learn/<int:book_id>')
def learn(book_id):
    """学习页面（多阶段模式）"""
    return render_template('learn-advanced.html', book_id=book_id)

@app.route('/review')
def review():
    """复习页面（新版：间隔 15 词 + 拼写验证）"""
    return render_template('review-advanced.html')

# ============== API 接口 ==============

@app.route('/api/books', methods=['GET'])
def get_books():
    """获取所有词书"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM books ORDER BY created_at DESC')
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(books)

@app.route('/api/books', methods=['POST'])
def create_book():
    """创建新书"""
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '书名不能为空'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO books (name) VALUES (?)', (name,))
        conn.commit()
        book_id = cursor.lastrowid
        conn.close()
        return jsonify({'id': book_id, 'name': name})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '书名已存在'}), 400

@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    """删除词书"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM words WHERE book_id = ?', (book_id,))
    cursor.execute('DELETE FROM books WHERE id = ?', (book_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/books/<int:book_id>/import', methods=['POST'])
def import_words(book_id):
    """导入单词"""
    if 'file' not in request.files:
        return jsonify({'error': '请上传文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '请选择文件'}), 400
    
    # 读取 CSV 文件
    words = []
    try:
        # 尝试 UTF-8 编码
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2:
                word = parts[0].strip()
                meaning = parts[1].strip()
                example = parts[2].strip() if len(parts) > 2 else ''
                words.append((book_id, word, meaning, example))
    except Exception as e:
        return jsonify({'error': f'解析文件失败：{str(e)}'}), 400
    
    if not words:
        return jsonify({'error': '没有找到有效的单词'}), 400
    
    # 保存到数据库
    conn = get_db()
    cursor = conn.cursor()
    success_count = 0
    duplicate_count = 0
    
    for word_data in words:
        try:
            cursor.execute('''
                INSERT INTO words (book_id, word, meaning, example)
                VALUES (?, ?, ?, ?)
            ''', word_data)
            success_count += 1
        except sqlite3.IntegrityError:
            duplicate_count += 1
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'imported': success_count,
        'duplicates': duplicate_count
    })

@app.route('/api/books/<int:book_id>/words')
def get_words(book_id):
    """获取词书单词列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, 
               lr.learned_at,
               lr.review_count,
               lr.next_review_at,
               lr.mastered
        FROM words w
        LEFT JOIN learning_records lr ON w.id = lr.word_id
        WHERE w.book_id = ?
        ORDER BY w.word
    ''', (book_id,))
    words = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(words)



@app.route('/api/learn/known', methods=['POST'])
def mark_as_known():
    """标记为"认识" - 进入多阶段学习流程阶段 1"""
    data = request.json
    word_id = data.get('word_id')
    book_id = data.get('book_id')
    
    if not word_id:
        return jsonify({'error': '缺少单词 ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 1. 加入/更新学习进度（阶段 1）
        cursor.execute('''
            INSERT OR REPLACE INTO learning_progress (word_id, book_id, stage, words_since_stage, last_practiced_at)
            VALUES (?, ?, 1, 0, ?)
        ''', (word_id, book_id, datetime.now()))
        
        # 2. 从待重学队列移除（如果存在）
        cursor.execute('DELETE FROM relearn_queue WHERE word_id = ?', (word_id,))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'stage': 1})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/learn/unknown', methods=['POST'])
def mark_as_unknown():
    """标记为"不认识" - 加入待重学队列，但需要间隔 15 个单词后才重新出现"""
    data = request.json
    word_id = data.get('word_id')
    book_id = data.get('book_id')
    
    if not word_id:
        return jsonify({'error': '缺少单词 ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 1. 加入待重学队列
        cursor.execute('''
            INSERT OR IGNORE INTO relearn_queue (word_id, book_id)
            VALUES (?, ?)
        ''', (word_id, book_id))
        
        # 2. 同时记录到 learning_progress，设置间隔计数器为 0
        # 这样需要再学 15 个其他单词后才会重新轮到
        cursor.execute('''
            INSERT OR REPLACE INTO learning_progress (word_id, book_id, stage, words_since_stage, last_practiced_at)
            VALUES (?, ?, 1, 0, ?)
        ''', (word_id, book_id, datetime.now()))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/learn/next', methods=['POST'])
def get_next_word():
    """获取下一个要学习的单词（支持多阶段 + 间隔）"""
    data = request.json
    book_id = data.get('book_id')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 优先从待重学队列获取，但需要检查间隔计数器（words_since_stage >= 15）
    cursor.execute('''
        SELECT w.*, lp.words_since_stage, 'relearn' as type, COALESCE(lp.stage, 0) as stage
        FROM relearn_queue rq
        JOIN words w ON rq.word_id = w.id
        LEFT JOIN learning_progress lp ON rq.word_id = lp.word_id
        WHERE rq.book_id = ?
          AND (lp.words_since_stage IS NULL OR lp.words_since_stage >= 15)
        ORDER BY rq.added_at
        LIMIT 1
    ''', (book_id,))
    word = cursor.fetchone()
    
    if word:
        row = dict(word)
        row['is_relearn'] = True
        conn.close()
        return jsonify(row)
    
    # 2. 检查多阶段学习中**间隔已到**的单词（words_since_stage >= 15）
    cursor.execute('''
        SELECT w.*, lp.stage, 'progress' as type
        FROM learning_progress lp
        JOIN words w ON lp.word_id = w.id
        WHERE lp.book_id = ? AND lp.stage > 0 AND lp.stage < 5 
              AND lp.words_since_stage >= 15
        ORDER BY lp.stage ASC, lp.last_practiced_at ASC
        LIMIT 1
    ''', (book_id,))
    word = cursor.fetchone()
    
    if word:
        row = dict(word)
        row['is_relearn'] = False
        conn.close()
        return jsonify(row)
    
    # 3. 获取未学习的新单词
    cursor.execute('''
        SELECT w.*, 0 as stage, 'new' as type
        FROM words w
        LEFT JOIN learning_progress lp ON w.id = lp.word_id
        WHERE w.book_id = ? AND lp.word_id IS NULL
        ORDER BY RANDOM()
        LIMIT 1
    ''', (book_id,))
    word = cursor.fetchone()
    conn.close()
    
    if word:
        row = dict(word)
        row['is_relearn'] = False
        return jsonify(row)
    else:
        # 没有新单词，也没有间隔已到的，返回完成消息
        return jsonify({'message': '这本词书已经学完啦！🎉'}), 200

@app.route('/api/learn/generate-options', methods=['POST'])
def generate_options():
    """生成选择题选项（4 个选项）"""
    data = request.json
    word_id = data.get('word_id')
    question_type = data.get('question_type')  # 'meaning' 或 'word'
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取目标单词
    cursor.execute('SELECT * FROM words WHERE id = ?', (word_id,))
    target = dict(cursor.fetchone())
    
    if not target:
        conn.close()
        return jsonify({'error': '单词不存在'}), 404
    
    # 获取同词书的其他单词作为干扰项
    cursor.execute('''
        SELECT word, meaning FROM words 
        WHERE book_id = (SELECT book_id FROM words WHERE id = ?) 
        AND id != ?
        ORDER BY RANDOM()
        LIMIT 3
    ''', (word_id, word_id))
    distractors = cursor.fetchall()
    conn.close()
    
    if question_type == 'meaning':
        # 单词→释义选择题
        correct = target['meaning']
        options = [correct] + [d['meaning'] for d in distractors]
    else:
        # 释义→单词选择题
        correct = target['word']
        options = [correct] + [d['word'] for d in distractors]
    
    # 打乱选项
    import random
    random.shuffle(options)
    
    return jsonify({
        'word_id': word_id,
        'word': target['word'],
        'meaning': target['meaning'],
        'question_type': question_type,
        'options': options,
        'correct': correct
    })

@app.route('/api/learn/answer', methods=['POST'])
def submit_answer():
    """提交答案（选择题/拼写）"""
    data = request.json
    word_id = data.get('word_id')
    book_id = data.get('book_id')
    question_type = data.get('question_type')  # 'meaning', 'word', 'spelling', 'meaning_spelling'
    user_answer = data.get('answer')
    correct_answer = data.get('correct')
    
    # 中文释义拼写使用模糊匹配（忽略标点符号和空格）
    if question_type == 'meaning_spelling':
        import re
        def normalize_chinese(text):
            # 移除所有标点符号和空白字符，只保留纯文字
            return re.sub(r'[，。、；：？！""\'\'（）【】《》,.!?;:()\[\]{}"\'`\s…\-—–~·@#$%^&*+=|\\<>?/]', '', text).strip()
        is_correct = normalize_chinese(user_answer) == normalize_chinese(correct_answer)
    else:
        is_correct = user_answer.strip().lower() == correct_answer.strip().lower()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取当前阶段
    cursor.execute('SELECT stage FROM learning_progress WHERE word_id = ?', (word_id,))
    row = cursor.fetchone()
    current_stage = row['stage'] if row else 0
    
    if is_correct:
        # 答对了，进入下一阶段，重置间隔计数
        next_stage = current_stage + 1
        
        if next_stage >= 4:
            # 完成所有阶段（阶段 4），加入复习计划
            from datetime import timedelta
            next_review = datetime.now() + timedelta(days=REVIEW_INTERVALS[0])
            cursor.execute('''
                INSERT OR REPLACE INTO learning_records (word_id, next_review_at, review_count)
                VALUES (?, ?, ?)
            ''', (word_id, next_review, 0))
            cursor.execute('DELETE FROM learning_progress WHERE word_id = ?', (word_id,))
            conn.commit()
            conn.close()
            return jsonify({
                'correct': True,
                'next_stage': 5,
                'completed': True
            })
        else:
            # 进入下一阶段，重置间隔计数为 0
            cursor.execute('''
                UPDATE learning_progress 
                SET stage = ?, words_since_stage = 0, correct_count = correct_count + 1, last_practiced_at = ?
                WHERE word_id = ?
            ''', (next_stage, datetime.now(), word_id))
            conn.commit()
            conn.close()
            return jsonify({
                'correct': True,
                'next_stage': next_stage,
                'completed': False,
                'message': f'进入阶段{next_stage}，还需学习 15 个其他单词后再次测试'
            })
    else:
        # 答错了，重置回阶段 1
        cursor.execute('''
            UPDATE learning_progress 
            SET stage = 1, words_since_stage = 0, wrong_count = wrong_count + 1, last_practiced_at = ?
            WHERE word_id = ?
        ''', (datetime.now(), word_id))
        conn.commit()
        conn.close()
        return jsonify({
            'correct': False,
            'correct_answer': correct_answer,
            'reset_to_stage': 1
        })

@app.route('/api/learn/update-intervals', methods=['POST'])
def update_intervals():
    """学习完一个单词后，更新所有进行中的单词的间隔计数"""
    data = request.json
    book_id = data.get('book_id')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 所有进行中的单词（阶段 1-3）间隔计数 +1
    # 包括重学队列的单词（stage=1）
    cursor.execute('''
        UPDATE learning_progress 
        SET words_since_stage = words_since_stage + 1
        WHERE book_id = ? AND stage >= 1 AND stage < 4
    ''', (book_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/review/stats')
def get_review_stats():
    """获取复习统计"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # 今日需要复习的单词数
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM learning_records
        WHERE next_review_at <= ? AND mastered = 0
    ''', (now,))
    today_count = cursor.fetchone()['count']
    
    # 总学习单词数
    cursor.execute('SELECT COUNT(*) as count FROM learning_records')
    total_learned = cursor.fetchone()['count']
    
    # 已掌握单词数
    cursor.execute('SELECT COUNT(*) as count FROM learning_records WHERE mastered = 1')
    mastered = cursor.fetchone()['count']
    
    # 待学习单词数（总单词数 - 已学习单词数）
    cursor.execute('''
        SELECT COUNT(*) as count FROM words
        WHERE book_id = 1 AND id NOT IN (SELECT word_id FROM learning_records)
    ''')
    remaining = cursor.fetchone()['count']
    
    # 已完成 4 阶段进入复习队列的单词数（learning_records 中的单词）
    cursor.execute('''
        SELECT COUNT(*) as count FROM learning_records
        WHERE word_id IN (SELECT id FROM words WHERE book_id = 1)
    ''')
    completed = cursor.fetchone()['count']
    
    conn.close()
    
    return jsonify({
        'today': today_count,
        'total_learned': total_learned,
        'mastered': mastered,
        'remaining': remaining,
        'completed': completed
    })

@app.route('/api/review/reset', methods=['POST'])
def reset_review():
    """重置单词的艾宾浩斯曲线（拼写错误时调用）"""
    data = request.json
    word_id = data.get('word_id')
    
    if not word_id:
        return jsonify({'error': '缺少单词 ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 重置学习记录：review_count=0, next_review_at=明天
        tomorrow = datetime.now() + timedelta(days=1)
        cursor.execute('''
            UPDATE learning_records
            SET review_count = 0, next_review_at = ?, mastered = 0
            WHERE word_id = ?
        ''', (tomorrow, word_id))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/review/update-intervals', methods=['POST'])
def update_review_intervals():
    """复习完一个单词后，更新所有重学单词的间隔计数"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 所有重学队列的单词间隔计数 +1
    # 确保只更新 stage >= 1 的记录（进行中的单词）
    cursor.execute('''
        UPDATE learning_progress 
        SET words_since_stage = words_since_stage + 1
        WHERE word_id IN (SELECT word_id FROM relearn_queue)
          AND stage >= 1
    ''')
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/review/forget', methods=['POST'])
def forget_word():
    """忘记了单词 - 加入重学队列，间隔 15 个单词后重新复习"""
    data = request.json
    word_id = data.get('word_id')
    
    if not word_id:
        return jsonify({'error': '缺少单词 ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取 book_id
        cursor.execute('SELECT book_id FROM words WHERE id = ?', (word_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': '单词不存在'}), 404
        book_id = row['book_id']
        
        # 1. 加入待重学队列（如果不存在）
        cursor.execute('''
            INSERT OR IGNORE INTO relearn_queue (word_id, book_id)
            VALUES (?, ?)
        ''', (word_id, book_id))
        
        # 2. 确保 learning_progress 记录存在，设置间隔计数器为 0
        # 先检查是否存在
        cursor.execute('SELECT id FROM learning_progress WHERE word_id = ?', (word_id,))
        if cursor.fetchone():
            # 存在则更新
            cursor.execute('''
                UPDATE learning_progress 
                SET stage = 1, words_since_stage = 0, last_practiced_at = ?
                WHERE word_id = ?
            ''', (datetime.now(), word_id))
        else:
            # 不存在则插入
            cursor.execute('''
                INSERT INTO learning_progress (word_id, book_id, stage, words_since_stage, last_practiced_at)
                VALUES (?, ?, 1, 0, ?)
            ''', (word_id, book_id, datetime.now()))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/review/spelling', methods=['POST'])
def submit_review_spelling():
    """提交复习拼写答案"""
    data = request.json
    word_id = data.get('word_id')
    answer = data.get('answer', '')
    correct = data.get('correct', '')
    
    if not word_id or not answer:
        return jsonify({'error': '缺少参数'}), 400
    
    is_correct = answer.lower() == correct.lower()
    
    conn = get_db()
    cursor = conn.cursor()
    
    if is_correct:
        # 拼写正确 → 进入下一个复习周期
        cursor.execute('''
            SELECT review_count FROM learning_records WHERE word_id = ?
        ''', (word_id,))
        row = cursor.fetchone()
        review_count = row['review_count'] if row else 0
        
        # 计算下一个复习间隔
        if review_count < len(REVIEW_INTERVALS):
            next_interval = REVIEW_INTERVALS[review_count]
            next_review = datetime.now() + timedelta(days=next_interval)
        else:
            next_review = datetime.now() + timedelta(days=REVIEW_INTERVALS[-1])
        
        cursor.execute('''
            UPDATE learning_records
            SET review_count = review_count + 1, next_review_at = ?
            WHERE word_id = ?
        ''', (next_review, word_id))
    else:
        # 拼写错误 → 重置曲线
        tomorrow = datetime.now() + timedelta(days=1)
        cursor.execute('''
            UPDATE learning_records
            SET review_count = 0, next_review_at = ?, mastered = 0
            WHERE word_id = ?
        ''', (tomorrow, word_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'correct': is_correct})

@app.route('/api/review/next', methods=['POST'])
def get_next_review():
    """获取下一个要复习的单词（支持重学队列）"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # 1. 优先从重学队列获取（忘记了的单词，间隔已满 15 个）
    # 修复：去掉 IS NULL 条件，只返回间隔已满的单词
    cursor.execute('''
        SELECT w.id, w.word, w.meaning, w.example,
               COALESCE(lp.words_since_stage, 0) as words_since_stage, 'relearn' as type
        FROM relearn_queue rq
        JOIN words w ON rq.word_id = w.id
        LEFT JOIN learning_progress lp ON rq.word_id = lp.word_id
        WHERE COALESCE(lp.words_since_stage, 0) >= 15
        ORDER BY rq.added_at
        LIMIT 1
    ''')
    
    relearn_word = cursor.fetchone()
    
    if relearn_word:
        row = dict(relearn_word)
        # 从重学队列移除
        cursor.execute('DELETE FROM relearn_queue WHERE word_id = ?', (row['id'],))
        conn.commit()
        conn.close()
        return jsonify({
            'id': row['id'],
            'word': row['word'],
            'meaning': row['meaning'],
            'example': row['example'],
            'review_count': 0,
            'is_relearn': True
        })
    
    # 2. 获取正常复习队列的单词
    cursor.execute('''
        SELECT w.id, w.word, w.meaning, w.example,
               lr.review_count, lr.next_review_at
        FROM learning_records lr
        JOIN words w ON lr.word_id = w.id
        WHERE lr.next_review_at <= ? AND lr.mastered = 0
        ORDER BY lr.next_review_at
        LIMIT 1
    ''', (now,))
    
    record = cursor.fetchone()
    conn.close()
    
    if record:
        return jsonify({
            'id': record['id'],
            'word': record['word'],
            'meaning': record['meaning'],
            'example': record['example'],
            'review_count': record['review_count'],
            'is_relearn': False
        })
    else:
        return jsonify({'message': '太棒了！今天没有需要复习的单词！🎉'}), 200

@app.route('/api/review/complete', methods=['POST'])
def complete_review():
    """完成复习"""
    data = request.json
    word_id = data.get('word_id')
    result = data.get('result')  # 'remember' or 'forget'
    
    if not word_id:
        return jsonify({'error': '缺少单词 ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取当前复习记录
    cursor.execute('''
        SELECT review_count FROM learning_records WHERE word_id = ?
    ''', (word_id,))
    record = cursor.fetchone()
    
    if not record:
        conn.close()
        return jsonify({'error': '未找到学习记录'}), 404
    
    review_count = record['review_count']
    
    if result == 'remember':
        # 记住了，进入下一个复习阶段
        review_count += 1
        if review_count >= len(REVIEW_INTERVALS):
            # 已掌握
            next_review = None
            mastered = 1
        else:
            # 计算下次复习时间
            days = REVIEW_INTERVALS[review_count]
            next_review = datetime.now() + timedelta(days=days)
            mastered = 0
    else:
        # 忘记了，重置复习进度
        review_count = 0
        next_review = datetime.now() + timedelta(days=REVIEW_INTERVALS[0])
        mastered = 0
    
    cursor.execute('''
        UPDATE learning_records
        SET review_count = ?, next_review_at = ?, mastered = ?
        WHERE word_id = ?
    ''', (review_count, next_review, mastered, word_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/words/<int:word_id>', methods=['DELETE'])
def reset_word(word_id):
    """重置单词学习记录"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM learning_records WHERE word_id = ?', (word_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/ai/generate-example', methods=['POST'])
def generate_example():
    """使用 AI 生成单词例句"""
    data = request.json
    word = data.get('word', '')
    meaning = data.get('meaning', '')
    
    if not word or not meaning:
        return jsonify({'error': '缺少单词或释义'}), 400
    
    if not DEEPSEEK_API_KEY:
        return jsonify({'error': '未配置 DeepSeek API Key，请在.env 文件中设置 DEEPSEEK_API_KEY'}), 500
    
    # 构建提示词
    prompt = f"""请为以下英语单词生成一个简单、地道的例句，并附上中文翻译：

单词：{word}
释义：{meaning}

要求：
1. 例句要简短（10-20 个单词）
2. 适合英语初学者
3. 返回格式：先英文例句，换行后写"中文："再加中文翻译
4. 例句中该单词用粗体标记（如 **{word}**）

示例格式：
She enjoys watching **drama** series.
中文：她喜欢看戏剧类电视剧。

请为"{word}"生成例句："""
    
    try:
        # 调用 DeepSeek API
        req_data = json.dumps({
            'model': DEEPSEEK_MODEL,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 100
        }).encode('utf-8')
        
        req = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=req_data,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
            },
            method='POST'
        )
        
        # 禁用 SSL 验证（容器环境可能需要）
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, timeout=30, context=context) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        example = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
        
        # 清理响应（去掉可能的引号）
        example = example.strip('"\'')
        
        return jsonify({
            'success': True,
            'example': example,
            'word': word
        })
        
    except Exception as e:
        return jsonify({'error': f'AI 生成失败：{str(e)}'}), 500

# 后台任务存储（简单内存存储，生产环境可用 Redis）
bg_tasks = {}

@app.route('/api/books/<int:book_id>/ai-generate-all', methods=['POST'])
def ai_generate_all_examples(book_id):
    """批量为词书中所有单词生成例句（后台任务模式）"""
    import uuid
    from datetime import datetime
    
    data = request.json or {}
    batch_mode = data.get('batchMode', False)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取没有例句的单词（全部，不限制数量）
    cursor.execute('''
        SELECT id, word, meaning
        FROM words
        WHERE book_id = ? AND (example IS NULL OR example = '')
    ''', (book_id,))
    
    words_without_examples = cursor.fetchall()
    total_count = len(words_without_examples)
    conn.close()
    
    if not words_without_examples:
        return jsonify({
            'success': True,
            'message': '所有单词都已有例句！',
            'total': 0
        })
    
    # 创建任务
    task_id = str(uuid.uuid4())
    bg_tasks[task_id] = {
        'book_id': book_id,
        'total': total_count,
        'processed': 0,
        'success_count': 0,
        'failed_count': 0,
        'status': 'running',
        'current_word': None,
        'error': None,
        'created_at': datetime.now(),
        'words': words_without_examples
    }
    
    # 在后台线程中执行
    import threading
    thread = threading.Thread(target=generate_examples_task, args=(task_id,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'taskId': task_id,
        'total': total_count,
        'message': f'已启动后台任务，共需生成 {total_count} 个例句'
    })

def generate_examples_task(task_id):
    """后台生成例句任务"""
    task = bg_tasks.get(task_id)
    if not task:
        return
    
    book_id = task['book_id']
    words = task['words']
    
    try:
        for i, word_row in enumerate(words):
            word_id = word_row['id']
            word = word_row['word']
            meaning = word_row['meaning']
            
            # 更新进度
            task['current_word'] = word
            task['processed'] = i + 1
            
            # 调用 AI 生成
            try:
                req_data = json.dumps({
                    'model': DEEPSEEK_MODEL,
                    'messages': [
                        {'role': 'user', 'content': f"为单词'{word}'（释义：{meaning}）生成一个简短地道的英语例句，只返回例句本身。"}
                    ],
                    'temperature': 0.7,
                    'max_tokens': 80
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    DEEPSEEK_API_URL,
                    data=req_data,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
                    },
                    method='POST'
                )
                
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(req, timeout=60, context=context) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                example = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip().strip('"\'')
                
                # 更新数据库
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('UPDATE words SET example = ? WHERE id = ?', (example, word_id))
                conn.commit()
                conn.close()
                
                task['success_count'] += 1
                
            except Exception as e:
                task['failed_count'] += 1
                print(f"生成 {word} 失败：{e}")
        
        # 完成
        task['status'] = 'completed'
        task['current_word'] = None
        
    except Exception as e:
        task['status'] = 'failed'
        task['error'] = str(e)
        print(f"任务 {task_id} 失败：{e}")

@app.route('/api/books/<int:book_id>/ai-generate-status/<task_id>', methods=['GET'])
def get_generate_status(book_id, task_id):
    """获取生成任务进度"""
    task = bg_tasks.get(task_id)
    if not task or task['book_id'] != book_id:
        return jsonify({'error': '任务不存在'}), 404
    
    progress = int((task['processed'] / task['total']) * 100) if task['total'] > 0 else 0
    
    return jsonify({
        'status': task['status'],
        'progress': progress,
        'processed': task['processed'],
        'total': task['total'],
        'success_count': task['success_count'],
        'failed_count': task['failed_count'],
        'current_word': task['current_word'],
        'error': task['error']
    })

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', type=str, default='0.0.0.0')
    args = parser.parse_args()
    
    # 创建模板目录
    os.makedirs('templates', exist_ok=True)
    
    # 初始化数据库
    init_db()
    
    port = args.port
    # Hugging Face Spaces 环境变量
    if os.environ.get('HF_SPACE_ID'):
        port = 7860
    
    print(f"\n📚 背单词网站启动中...")
    print(f"🌐 访问地址：http://{args.host}:{port}")
    print(f"\n按 Ctrl+C 停止服务\n")
    
    app.run(host=args.host, port=port, debug=False)
