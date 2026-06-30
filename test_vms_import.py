import sys
import ast

def check_syntax(filepath):
    try:
        with open(filepath, 'r') as file:
            ast.parse(file.read(), filename=filepath)
        print("Syntax OK")
    except SyntaxError as e:
        print(f"SyntaxError: {e}")

check_syntax("backend/app/api/vms.py")
