import json
import os

DB_FOLDER = 'db'
VIP_FOLDER = os.path.join(DB_FOLDER, 'vip')
CLI_FOLDER = os.path.join(DB_FOLDER, 'cli')
DYN_FILE = os.path.join(DB_FOLDER, 'dyn_config.json')

# Helper function to ensure folders exist
def _ensure_dir(path):
    os.makedirs(os.path.dirname(path) if '.' in os.path.basename(path) else path, exist_ok=True)

def get_path(type: bool, object):
    object = str(object)
    folder = CLI_FOLDER if type else VIP_FOLDER
    try:
        for filename in os.listdir(folder):
            if object in filename and filename.endswith('.json'):
                return os.path.join(folder, filename)
    except FileNotFoundError:
        pass
    return False

def get_chat_ids(type: bool):
    folder = CLI_FOLDER if type else VIP_FOLDER
    try:
        return [filename.replace('.json', '') for filename in os.listdir(folder) if filename.endswith('.json')]
    except FileNotFoundError:
        return []

def get_chat_names(type: bool):
    folder = CLI_FOLDER if type else VIP_FOLDER
    chat_names = []
    try:
        for filename in os.listdir(folder):
            if filename.endswith('.json'):
                path = os.path.join(folder, filename)
                name = get_db(True, path, 0, None)
                if name:  # فقط اگر اسم معتبر بود اضافه کنه
                    chat_names.append(name)
    except FileNotFoundError:
        pass
    return chat_names

def mk_db(type: bool, object: str, object_2):
    folder = CLI_FOLDER if type else VIP_FOLDER
    path = os.path.join(folder, f'{str(object)}.json')
    
    try:
        _ensure_dir(path)
        with open(path, 'w', encoding='utf-8') as file:
            json.dump([{"role": "data", "content": str(object_2)}], file, indent=4)
        return True
    except Exception:
        return False

def rm_db(path):
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False

def edit_db(type: bool, path, target, value):
    try:
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
        if type:
            for item in data:
                if item.get("content") == str(target):
                    item['content'] = str(value)
        else:
            data.append({
                "role": str(target),
                "content": str(value)
            })
            
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)
        return True
    except (FileNotFoundError, json.JSONDecodeError):
        return False

def dump_db(type: bool, path, target, value):
    try:
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
        if type:
            data = [item for item in data if item.get("content") != str(value)]
        else:
            data = [item for item in data if item.get("role") != str(target)]
            
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)
        return True
    except (FileNotFoundError, json.JSONDecodeError):
        return False

def get_db(type: bool, path, index, target):
    try:
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
        if type:
            return data[index].get('content')
        else:
            return [item.get('content') for item in data if item.get('role') == target]
    except (FileNotFoundError, json.JSONDecodeError, IndexError):
        return False

def exp_db(path):
    try:
        with open(path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return False

def get_dyn(target):
    try:
        with open(DYN_FILE, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data.get(target)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def edit_dyn(target, value):
    try:
        if os.path.exists(DYN_FILE):
            with open(DYN_FILE, 'r', encoding='utf-8') as file:
                data = json.load(file)
        else:
            data = {}
            
        data[target] = value
        
        _ensure_dir(DYN_FILE)
        with open(DYN_FILE, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)
        return True
    except Exception:
        return False
