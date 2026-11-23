
import json
import os
import tempfile

DB_FOLDER = "db"
VIP_FOLDER = os.path.join(DB_FOLDER, "vip")
CLI_FOLDER = os.path.join(DB_FOLDER, "cli")
DYN_FILE = os.path.join(DB_FOLDER, "dyn_config.json")


# -------------------------
# Internal helpers
# -------------------------

def _ensure_dir(path):
    """Ensure the parent directory of a file, or the directory itself, exists."""
    if not path:
        return False

    path = os.fspath(path)
    extension = os.path.splitext(os.path.basename(path))[1]

    folder = os.path.dirname(path) if extension else path

    if folder:
        os.makedirs(folder, exist_ok=True)

    return True


def _read_json(path):
    """Read JSON safely. Return False on invalid/unreadable files."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _write_json(path, data):
    """
    Write JSON atomically to prevent partial/corrupted files
    if the process stops during writing.
    """
    temp_path = None

    try:
        _ensure_dir(path)

        folder = os.path.dirname(path) or "."

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=folder,
            delete=False,
            suffix=".tmp"
        ) as file:
            temp_path = file.name

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=True
            )

            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_path, path)
        return True

    except (OSError, TypeError, ValueError):
        return False

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _get_folder(type):
    """Return the appropriate database folder."""
    return CLI_FOLDER if type else VIP_FOLDER


def _is_valid_db(data):
    """Validate the basic database structure."""
    return isinstance(data, list) and all(
        isinstance(item, dict) for item in data
    )


# -------------------------
# Path / ID functions
# -------------------------

def get_path(type: bool, object):
    object = str(object)
    folder = _get_folder(type)

    try:
        for filename in os.listdir(folder):
            if object in filename and filename.endswith(".json"):
                return os.path.join(folder, filename)

    except OSError:
        pass

    return False


def get_chat_ids(type: bool):
    folder = _get_folder(type)

    try:
        return [
            filename[:-5]
            for filename in os.listdir(folder)
            if filename.endswith(".json")
        ]

    except OSError:
        return []


def get_chat_names(type: bool):
    folder = _get_folder(type)
    chat_names = []

    try:
        for filename in os.listdir(folder):
            if not filename.endswith(".json"):
                continue

            path = os.path.join(folder, filename)
            name = get_db(True, path, 0, None)

            if name:
                chat_names.append(name)

    except OSError:
        pass

    return chat_names


# -------------------------
# Database management
# -------------------------

def mk_db(type: bool, object: str, object_2):
    folder = _get_folder(type)
    path = os.path.join(folder, f"{str(object)}.json")

    data = [
        {
            "role": "data",
            "content": str(object_2)
        }
    ]

    return _write_json(path, data)


def rm_db(path):
    try:
        os.remove(path)
        return True

    except OSError:
        return False


def edit_db(type: bool, path, target, value):
    data = _read_json(path)

    if not _is_valid_db(data):
        return False

    if type:
        for item in data:
            if item.get("content") == str(target):
                item["content"] = str(value)

    else:
        data.append({
            "role": str(target),
            "content": str(value)
        })

    return _write_json(path, data)


def dump_db(type: bool, path, target, value):
    data = _read_json(path)

    if not _is_valid_db(data):
        return False

    if type:
        data = [
            item for item in data
            if item.get("content") != str(value)
        ]

    else:
        data = [
            item for item in data
            if item.get("role") != str(target)
        ]

    return _write_json(path, data)


def get_db(type: bool, path, index, target):
    data = _read_json(path)

    if not _is_valid_db(data):
        return False

    try:
        if type:
            return data[index].get("content")

        return [
            item.get("content")
            for item in data
            if item.get("role") == target
        ]

    except (IndexError, TypeError):
        return False


def exp_db(path):
    return _read_json(path)


# -------------------------
# Dynamic config
# -------------------------

def get_dyn(target):
    data = _read_json(DYN_FILE)

    if not isinstance(data, dict):
        return None

    return data.get(target)


def edit_dyn(target, value):
    data = _read_json(DYN_FILE)

    # Config file doesn't exist yet
    if data is False:
        data = {}

    # Prevent writing into a corrupted/unexpected config structure
    if not isinstance(data, dict):
        return False

    data[target] = value

    return _write_json(DYN_FILE, data)
