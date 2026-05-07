#!/usr/bin/env python3
"""
📚 背单词网站 - Vercel Serverless 版本
"""
import json
import sqlite3
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs

# Vercel Serverless 数据库路径
DB_PATH = '/var/task/vocabulary.db'

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def handler(event, context):
    """Vercel Serverless 处理函数"""
    
    path = event.get('rawPath', event.get('path', '/'))
    method = event.get('method', 'GET')
    
    # API 路由
    if path == '/api/review/stats' and method == 'GET':
        return api_review_stats(event)
    elif path == '/api/review/next' and method == 'GET':
        return api_review_next(event)
    elif path == '/api/review/complete' and method == 'POST':
        return api_review_complete(event)
    elif path == '/api/review/forget' and method == 'POST':
        return api_review_forget(event)
    elif path == '/api/learn/next' and method == 'GET':
        return api_learn_next(event)
    elif path == '/api/learn/complete' and method == 'POST':
        return api_learn_complete(event)
    elif path == '/api/books' and method == 'GET':
        return api_books(event)
    # 静态文件/前端
    elif path == '/' or path == '':
        return serve_file('templates/index.html')
    elif path.startswith('/templates/'):
        return serve_file(path[1:])
    elif path == '/favicon.ico':
        return {'statusCode': 404, 'body': ''}
    else:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Not found'})
        }

def api_review_stats(event):
    """获取复习统计"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 今日待复习
        cursor.execute('''
            SELECT COUNT(*) FROM reviews 
            WHERE due_date <= ? AND completed = 0
        ''', (today,))
        remaining = cursor.fetchone()[0] or 0
        
        # 已学单词
        cursor.execute('SELECT COUNT(*) FROM reviews WHERE stage > 0')
        completed = cursor.fetchone()[0] or 0
        
        # 已掌握
        cursor.execute('SELECT COUNT(*) FROM reviews WHERE stage >= 8')
        mastered = cursor.fetchone()[0] or 0
        
        # 待学习
        cursor.execute('SELECT COUNT(*) FROM reviews WHERE stage = 0')
        new_words = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'remaining': remaining,
                'completed': completed,
                'mastered': mastered,
                'new_words': new_words
            })
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_review_next(event):
    """获取下一个复习单词"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 先查重学队列
        cursor.execute('''
            SELECT word, meaning, example 
            FROM relearn_queue 
            WHERE created_at >= datetime('now', '-1 day')
            ORDER BY created_at
            LIMIT 1
        ''')
        row = cursor.fetchone()
        
        if row:
            word_data = {'word': row[0], 'meaning': row[1], 'example': row[2]}
            # 从重学队列移除
            cursor.execute('DELETE FROM relearn_queue WHERE word = ?', (row[0],))
            conn.commit()
            conn.close()
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'word': word_data, 'from_relearn': True})
            }
        
        # 查正常复习
        cursor.execute('''
            SELECT r.word, r.meaning, r.example 
            FROM reviews r 
            WHERE r.due_date <= ? AND r.completed = 0 
            LIMIT 1
        ''', (today,))
        row = cursor.fetchone()
        
        if row:
            word_data = {'word': row[0], 'meaning': row[1], 'example': row[2]}
            conn.close()
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'word': word_data, 'from_relearn': False})
            }
        
        conn.close()
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'word': None, 'message': 'No reviews due'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_review_complete(event):
    """标记复习完成"""
    try:
        data = json.loads(event.get('body', '{}'))
        word = data.get('word')
        quality = data.get('quality', 1)
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 更新复习记录
        cursor.execute('''
            UPDATE reviews 
            SET stage = stage + 1,
                due_date = date('now', '+' || 
                    CASE 
                        WHEN stage = 0 THEN 1
                        WHEN stage = 1 THEN 2
                        WHEN stage = 2 THEN 4
                        WHEN stage = 3 THEN 7
                        WHEN stage = 4 THEN 15
                        WHEN stage = 5 THEN 30
                        WHEN stage = 6 THEN 60
                        ELSE 90
                    END || ' days'),
                completed = 0
            WHERE word = ?
        ''', (word,))
        
        conn.commit()
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_review_forget(event):
    """标记忘记了 - 加入重学队列"""
    try:
        data = json.loads(event.get('body', '{}'))
        word = data.get('word')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取单词信息
        cursor.execute('SELECT word, meaning, example FROM reviews WHERE word = ?', (word,))
        row = cursor.fetchone()
        
        if row:
            # 加入重学队列
            cursor.execute('''
                INSERT INTO relearn_queue (word, meaning, example, created_at)
                VALUES (?, ?, ?, datetime('now'))
            ''', (row[0], row[1], row[2]))
            
            # 重置复习进度
            cursor.execute('''
                UPDATE reviews SET stage = 0, due_date = date('now', '+1 day')
                WHERE word = ?
            ''', (word,))
            
            conn.commit()
        
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_learn_next(event):
    """获取下一个新单词"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT word, meaning, example 
            FROM reviews 
            WHERE stage = 0 
            LIMIT 1
        ''')
        row = cursor.fetchone()
        
        if row:
            word_data = {'word': row[0], 'meaning': row[1], 'example': row[2]}
            conn.close()
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'word': word_data})
            }
        
        conn.close()
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'word': None, 'message': 'No new words'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_learn_complete(event):
    """标记学习完成"""
    try:
        data = json.loads(event.get('body', '{}'))
        word = data.get('word')
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE reviews 
            SET stage = 1, due_date = date('now', '+1 day')
            WHERE word = ?
        ''', (word,))
        
        conn.commit()
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def api_books(event):
    """获取词书列表"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM books ORDER BY created_at DESC')
        rows = cursor.fetchall()
        
        books = [{'id': row['id'], 'name': row['name'], 'created_at': row['created_at']} for row in rows]
        
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'books': books})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def serve_file(path):
    """ serve 静态文件（简化版）"""
    try:
        # 这里简化处理，返回简单 HTML
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/html'},
            'body': '''<!DOCTYPE html>
<html>
<head><title>背单词</title></head>
<body>
<h1>📚 背单词网站</h1>
<p>Serverless 版本运行中！</p>
<p><a href="/api/review/stats">查看统计 API</a></p>
</body>
</html>'''
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html'},
            'body': f'<h1>Error</h1><p>{e}</p>'
        }

# Vercel 入口
app = handler
