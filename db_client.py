import json
import os

DB_FOLDER = 'db'
VIP_FOLDER = os.path.join(DB_FOLDER, 'vip')
CLI_FOLDER = os.path.join(DB_FOLDER, 'cli')
DYN_FILE = os.path.join(DB_FOLDER, 'dyn_config.json')

def get_path(type: bool, object):
    object = str(object)
    if type:
        for filename in os.listdir(CLI_FOLDER):
            if object in filename:
                return os.path.join(CLI_FOLDER, filename)
    else:
        for filename in os.listdir(VIP_FOLDER):
            if object in filename:
                return os.path.join(VIP_FOLDER, filename)
    return False
def get_chat_ids(type: bool):
    if type:
        return [filename.split('.json')[0] for filename in os.listdir(CLI_FOLDER)]
    else:
        return [filename.split('.json')[0] for filename in os.listdir(VIP_FOLDER)]
def get_chat_names(type: bool):
    chat_names = []
    if type:
        for filename in os.listdir(CLI_FOLDER):
            path = os.path.join(CLI_FOLDER, filename)
            chat_names.append(get_db(True, path, 0, None))
    else:
        for filename in os.listdir(VIP_FOLDER):
            path = os.path.join(VIP_FOLDER, filename)
            chat_names.append(get_db(True, path, 0, None))
    return chat_names

def mk_db(type: bool, object: str, object_2):
    object = str(object)
    object_2 = str(object_2)
    if type:
        path = os.path.join(CLI_FOLDER, f'{object}.json')
    else:
        path = os.path.join(VIP_FOLDER, f'{object}.json')
    with open(path, 'w') as file:
        json.dump([{"role":"data", "content": object_2}], file, indent=4)
        return True
    return False
def rm_db(path):
    if os.path.exists(path):
        os.remove(path)
        return True
    return False

def edit_db(type: bool, path, target, value):
    value = str(value)
    target = str(target)
    with open(path, 'r') as file:
        data = json.load(file)
    if type:
        for i, item in enumerate(data):
            if item["content"] == target:
                data[i]['content'] = value
    else:
        new_item = {
            "role": target,
            "content": value
        }
        data.append(new_item)
    with open(path, 'w') as file:
        json.dump(data, file, indent=4)
        return True
    return False
def dump_db(type: bool, path, target, value):
    value = str(value)
    target = str(target)
    with open(path, 'r') as file:
        data = json.load(file)
    if type:
        data = [item for item in data if item["content"] != value]
    else:
        data = [item for item in data if item["role"] != target]
    with open(path, 'w') as file:
        json.dump(data, file, indent=4)
        return True
    return False
def get_db(type: bool, path, index, target):
    with open(path, 'r') as file:
        data = json.load(file)
    if type:
        return data[index]['content']
    else:
        return [item['content'] for item in data if item['role'] == target]
def exp_db(path):
    if os.path.exists(path):
        with open(path, 'r') as file:
            data = json.load(file)
        return data
    return False

def get_dyn(target):
    with open(DYN_FILE, 'r') as file:
        data = json.load(file)
    return data[target]
def edit_dyn(target, value):
    with open(DYN_FILE, 'r') as file:
        data = json.load(file)
    data[target] = value
    with open(DYN_FILE, 'w') as file:
        json.dump(data, file, indent=4)
        return True
    return False


