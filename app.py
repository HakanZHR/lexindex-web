"""
Lexindex Web - English Turkish Dictionary & Quiz System
Flask web version of the desktop app for Railway deployment
"""

from flask import Flask, render_template, request, jsonify, session, send_file
from flask_cors import CORS
import pandas as pd
import os
import json
import random
import requests
from deep_translator import GoogleTranslator
import tempfile
from pathlib import Path
import uuid
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = 'lexindex-web-secret-key-2024'
CORS(app)

# API Configuration
MERRIAM_WEBSTER_DICT_KEY = "e7a49248-5922-4466-aad5-ea05ed542841"
MERRIAM_WEBSTER_THESAURUS_KEY = "08d3b958-e70c-4cfd-9ed1-74bd83f3c51c"
MERRIAM_WEBSTER_DICT_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json"
MERRIAM_WEBSTER_THESAURUS_URL = "https://www.dictionaryapi.com/api/v3/references/thesaurus/json"

# Global data storage
all_words = []
all_questions = []
favorites_data = []

# Audio Manager for Web
class WebAudioManager:
    def __init__(self):
        self.base_audio_url = "https://media.merriam-webster.com/audio/prons/en/us/mp3/"
    
    def extract_audio_info_from_api_response(self, api_response):
        audio_files = []
        
        if not isinstance(api_response, list) or not api_response:
            return audio_files
        
        for entry in api_response:
            if not isinstance(entry, dict):
                continue
                
            if "hwi" in entry and "prs" in entry["hwi"]:
                for prs in entry["hwi"]["prs"]:
                    if "sound" in prs and "audio" in prs["sound"]:
                        audio_filename = prs["sound"]["audio"]
                        if audio_filename:
                            subdirectory = self.get_audio_subdirectory(audio_filename)
                            audio_url = f"{self.base_audio_url}{subdirectory}/{audio_filename}.mp3"
                            
                            audio_info = {
                                "url": audio_url,
                                "filename": audio_filename,
                                "pronunciation": prs.get("mw", ""),
                                "entry_id": entry.get("meta", {}).get("id", "")
                            }
                            audio_files.append(audio_info)
        
        return audio_files
    
    def get_audio_subdirectory(self, filename):
        if not filename:
            return "bix"
        
        if filename.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
            return "number"
        
        if filename.startswith(('_', '.', '!', '?', ',')):
            return "bix"
        
        if filename.startswith("gg"):
            return "gg"
        
        return filename[0].lower()

# API Manager
class WebAPIManager:
    def __init__(self):
        self.cache = {}
        self.dict_key = MERRIAM_WEBSTER_DICT_KEY
        self.thesaurus_key = MERRIAM_WEBSTER_THESAURUS_KEY
        self.session = requests.Session()
        self.audio_manager = WebAudioManager()
    
    def get_word_data(self, word):
        try:
            word = word.lower().strip()
            
            if word in self.cache:
                return self.cache[word]
            
            dict_data = self.get_dictionary_data(word)
            if "error" in dict_data:
                return dict_data
            
            thesaurus_data = self.get_thesaurus_data(word)
            
            combined_data = dict_data.copy()
            combined_data.update(thesaurus_data)
            combined_data['Turkish_Translation'] = self.translate_to_turkish(word)
            
            self.cache[word] = combined_data
            return combined_data
                
        except requests.exceptions.RequestException:
            return {"error": "network_error", "word": word}
        except Exception:
            return {"error": "unknown_error", "word": word}
    
    def get_dictionary_data(self, word):
        try:
            dict_url = f"{MERRIAM_WEBSTER_DICT_URL}/{word}?key={self.dict_key}"
            response = self.session.get(dict_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], str):
                        return {"error": "word_not_found", "word": word, "suggestions": data[:5]}
                    
                    return self.process_dictionary_response(data, word)
                else:
                    return {"error": "word_not_found", "word": word}
            else:
                return {"error": "api_error", "word": word}
                
        except Exception:
            return {"error": "api_error", "word": word}
    
    def get_thesaurus_data(self, word):
        try:
            thesaurus_url = f"{MERRIAM_WEBSTER_THESAURUS_URL}/{word}?key={self.thesaurus_key}"
            response = self.session.get(thesaurus_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if isinstance(data, list) and len(data) > 0 and not isinstance(data[0], str):
                    return self.process_thesaurus_response(data, word)
                    
            return {"Thesaurus_Data": "No thesaurus data available"}
                
        except Exception:
            return {"Thesaurus_Data": "Thesaurus data unavailable"}
    
    def process_dictionary_response(self, data, word):
        word_data = {
            "Word": word.title(),
            "Dictionary_Data": {}
        }
        
        if data and isinstance(data, list):
            all_entries = []
            
            for entry in data:
                entry_data = {
                    "headword": "",
                    "part_of_speech": "",
                    "pronunciation": "",
                    "etymology": "",
                    "definitions": [],
                    "examples": []
                }
                
                if "meta" in entry and "id" in entry["meta"]:
                    entry_data["headword"] = entry["meta"]["id"].split(":")[0].title()
                
                if "fl" in entry:
                    entry_data["part_of_speech"] = entry["fl"]
                
                if "hwi" in entry and "prs" in entry["hwi"]:
                    pronunciations = []
                    for prs in entry["hwi"]["prs"]:
                        if "mw" in prs:
                            pronunciations.append(f"/{prs['mw']}/")
                    entry_data["pronunciation"] = ", ".join(pronunciations)
                
                if "et" in entry:
                    etymology_parts = []
                    for et_item in entry["et"]:
                        if isinstance(et_item, list) and len(et_item) > 1:
                            if et_item[0] == "text":
                                text = et_item[1]
                                for tag in ["{it}", "{/it}", "{et_link|", "|}"]:
                                    text = text.replace(tag, "")
                                etymology_parts.append(text.strip())
                    entry_data["etymology"] = " ".join(etymology_parts)
                
                if "def" in entry:
                    for definition_group in entry["def"]:
                        if "sseq" in definition_group:
                            for sense_sequence in definition_group["sseq"]:
                                for sense in sense_sequence:
                                    if isinstance(sense, list) and len(sense) > 1:
                                        sense_data = sense[1]
                                        if isinstance(sense_data, dict) and "dt" in sense_data:
                                            for dt_item in sense_data["dt"]:
                                                if dt_item[0] == "text":
                                                    def_text = dt_item[1]
                                                    for tag in ["{bc}", "{sx|", "|}", "{a_link|", "}"]:
                                                        def_text = def_text.replace(tag, "")
                                                    entry_data["definitions"].append(def_text.strip())
                                                
                                                elif dt_item[0] == "vis":
                                                    for vis_item in dt_item[1]:
                                                        if "t" in vis_item:
                                                            example = vis_item["t"]
                                                            for tag in ["{wi}", "{/wi}", "{it}", "{/it}"]:
                                                                example = example.replace(tag, "")
                                                            entry_data["examples"].append(example.strip())
                
                if "shortdef" in entry:
                    for short_def in entry["shortdef"]:
                        if short_def not in entry_data["definitions"]:
                            entry_data["definitions"].append(short_def)
                
                all_entries.append(entry_data)
            
            word_data["Dictionary_Data"] = all_entries
            
            if all_entries:
                first_entry = all_entries[0]
                word_data["Word"] = first_entry["headword"] or word.title()
                word_data["Part_of_Speech"] = first_entry["part_of_speech"]
                word_data["Main_Definition"] = first_entry["definitions"][0] if first_entry["definitions"] else ""
                word_data["Main_Example"] = first_entry["examples"][0] if first_entry["examples"] else ""
                word_data["Pronunciation"] = first_entry["pronunciation"]
        
        audio_files = self.audio_manager.extract_audio_info_from_api_response(data)
        word_data["Audio_Files"] = audio_files
        
        return word_data
    
    def process_thesaurus_response(self, data, word):
        thesaurus_data = {"Thesaurus_Data": []}
        
        if data and isinstance(data, list):
            for entry in data:
                entry_data = {
                    "headword": "",
                    "part_of_speech": "",
                    "synonyms": [],
                    "antonyms": [],
                    "related_words": [],
                    "near_antonyms": []
                }
                
                if "meta" in entry and "id" in entry["meta"]:
                    entry_data["headword"] = entry["meta"]["id"].split(":")[0].title()
                
                if "fl" in entry:
                    entry_data["part_of_speech"] = entry["fl"]
                
                if "meta" in entry:
                    meta = entry["meta"]
                    for key, attr in [("syns", "synonyms"), ("ants", "antonyms"), 
                                     ("rel", "related_words"), ("near", "near_antonyms")]:
                        if key in meta:
                            for group in meta[key]:
                                entry_data[attr].extend(group)
                
                thesaurus_data["Thesaurus_Data"].append(entry_data)
        
        return thesaurus_data
    
    def get_pronunciation_audio_url(self, word_data):
        audio_files = word_data.get("Audio_Files", [])
        
        if not audio_files:
            return None
        
        return audio_files[0]["url"]
    
    def translate_to_turkish(self, text):
        try:
            translator = GoogleTranslator(source='en', target='tr')
            return translator.translate(text)
        except Exception:
            return "Çeviri bulunamadı"

# Initialize API manager
api_manager = WebAPIManager()

def load_database():
    """Load Excel files from database folder"""
    global all_words, all_questions
    
    all_words = []
    all_questions = []
    
    database_folder = Path("database")
    if not database_folder.exists():
        database_folder.mkdir()
        return
    
    excel_files = list(database_folder.glob("*.xlsx")) + list(database_folder.glob("*.xls"))
    
    for file_path in excel_files:
        try:
            df = pd.read_excel(file_path, engine='openpyxl' if file_path.suffix == '.xlsx' else None)
            df.columns = df.columns.str.strip()
            
            if df.empty:
                continue
                
            first_column = df.columns[0].lower()
            
            if first_column == "question":
                for idx, row in df.iterrows():
                    question = str(row.get(df.columns[0], "")).strip() if pd.notna(row.get(df.columns[0])) else ""
                    options = []
                    answer = ""
                    explain = ""
                    
                    for col in df.columns:
                        col_lower = col.lower()
                        if col_lower == "question":
                            question = str(row.get(col, "")).strip() if pd.notna(row.get(col)) else ""
                        elif col_lower.startswith("option"):
                            option_text = str(row.get(col, "")).strip() if pd.notna(row.get(col)) else ""
                            if option_text:
                                options.append(option_text)
                        elif col_lower == "answer":
                            answer = str(row.get(col, "")).strip() if pd.notna(row.get(col)) else ""
                        elif col_lower == "explain":
                            explain = str(row.get(col, "")).strip() if pd.notna(row.get(col)) else ""
                    
                    if question and answer and len(question) > 10 and len(options) >= 2:
                        question_data = {
                            "Question": question,
                            "Options": options,
                            "Answer": answer,
                            "Explain": explain or "No explanation available."
                        }
                        all_questions.append(question_data)
            
            elif first_column == "word":
                for idx, row in df.iterrows():
                    word = ""
                    for col in df.columns:
                        if col.lower() == "word":
                            word = str(row.get(col, "")).strip() if pd.notna(row.get(col)) else ""
                            break
                    
                    if word:
                        all_words.append({"Word": word})
                        
        except Exception as e:
            print(f"Error loading {file_path.name}: {e}")

def load_favorites():
    """Load favorites from JSON file"""
    global favorites_data
    try:
        favorites_file = Path("favorites.json")
        if favorites_file.exists():
            with open(favorites_file, 'r', encoding='utf-8') as f:
                favorites_data = json.load(f)
        else:
            favorites_data = []
    except Exception as e:
        print(f"Error loading favorites: {e}")
        favorites_data = []

def save_favorites():
    """Save favorites to JSON file"""
    try:
        with open("favorites.json", 'w', encoding='utf-8') as f:
            json.dump(favorites_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving favorites: {e}")

# Load initial data
load_database()
load_favorites()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def search_word():
    data = request.get_json()
    word = data.get('word', '').strip()
    
    if not word:
        return jsonify({"error": "No word provided"}), 400
    
    result = api_manager.get_word_data(word)
    return jsonify(result)

@app.route('/api/random-words')
def get_random_words():
    if not all_words:
        return jsonify([])
    
    random_words = random.sample(all_words, min(16, len(all_words)))
    return jsonify(random_words)

@app.route('/api/quiz/random')
def get_random_quiz():
    if not all_questions:
        return jsonify({"error": "No questions available"})
    
    question = random.choice(all_questions)
    return jsonify(question)

@app.route('/api/quiz/check', methods=['POST'])
def check_quiz_answer():
    data = request.get_json()
    selected_option = data.get('selected_option', '')
    correct_answer = data.get('correct_answer', '')
    
    # Process answer checking logic
    correct_answer_ref = correct_answer.upper().strip()
    correct_option_text = ""
    
    if correct_answer_ref.startswith("OPTION"):
        try:
            option_number = int(correct_answer_ref.replace("OPTION", "")) - 1
            options = data.get('options', [])
            if 0 <= option_number < len(options):
                correct_option_text = options[option_number]
            else:
                correct_option_text = selected_option
        except ValueError:
            correct_option_text = selected_option
    else:
        correct_option_text = correct_answer_ref
    
    is_correct = selected_option.strip().lower() == correct_option_text.strip().lower()
    
    return jsonify({
        "is_correct": is_correct,
        "correct_answer": correct_option_text
    })

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    return jsonify(favorites_data)

@app.route('/api/favorites', methods=['POST'])
def add_favorite():
    data = request.get_json()
    word_data = data.get('word_data')
    
    if not word_data:
        return jsonify({"error": "No word data provided"}), 400
    
    word = word_data.get("Word", "")
    
    # Check if already in favorites
    if not any(fav["Word"].lower() == word.lower() for fav in favorites_data):
        favorites_data.append(word_data)
        save_favorites()
        return jsonify({"success": True, "message": f"'{word}' added to favorites"})
    else:
        return jsonify({"success": False, "message": f"'{word}' already in favorites"})

@app.route('/api/favorites/<word>', methods=['DELETE'])
def remove_favorite(word):
    global favorites_data
    original_count = len(favorites_data)
    favorites_data = [fav for fav in favorites_data if fav["Word"].lower() != word.lower()]
    
    if len(favorites_data) < original_count:
        save_favorites()
        return jsonify({"success": True, "message": f"'{word}' removed from favorites"})
    else:
        return jsonify({"success": False, "message": f"'{word}' not found in favorites"})

@app.route('/api/favorites/clear', methods=['DELETE'])
def clear_favorites():
    global favorites_data
    favorites_data = []
    save_favorites()
    return jsonify({"success": True, "message": "All favorites cleared"})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file and file.filename.lower().endswith(('.xlsx', '.xls')):
        filename = secure_filename(file.filename)
        
        # Ensure database folder exists
        database_folder = Path("database")
        database_folder.mkdir(exist_ok=True)
        
        # Save the file
        file_path = database_folder / filename
        file.save(file_path)
        
        # Reload database
        load_database()
        
        return jsonify({
            "success": True, 
            "message": f"File '{filename}' uploaded successfully",
            "word_count": len(all_words),
            "question_count": len(all_questions)
        })
    else:
        return jsonify({"error": "Invalid file type. Please upload .xlsx or .xls files"}), 400

@app.route('/api/stats')
def get_stats():
    return jsonify({
        "word_count": len(all_words),
        "question_count": len(all_questions),
        "favorites_count": len(favorites_data)
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)