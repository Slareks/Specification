import json
import sys

end_result = {"message":{"status":"non-compliant"}}
message={}

def write_to_json(text):
    with open('json_log.json', 'w', encoding='utf-8') as f:
        json.dump(text, f, ensure_ascii=False, indent=4)

def get_ssh_config_log(path_to_sshd, json_with_defaults):
    with open(path_to_sshd, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
        with open(json_with_defaults, 'r', encoding='utf-8') as f:
            defaults = json.load(f)
            for key in defaults.keys():
                for line in all_lines:
                    if key in line and "#" not in line:
                        splited_line = line.split()
                        if defaults[key] == splited_line[-1]:
                            message.update({f"{key}": splited_line[-1]})
                            end_result["message"].update(message)
                        else:
                            message.update({f"{key}": splited_line[-1]})
                            end_result["message"]["status"] = "compliant"
                            write_to_json(end_result)
        write_to_json(end_result)

if __name__ == '__main__':
    get_ssh_config_log(sys.argv[1], sys.argv[2])