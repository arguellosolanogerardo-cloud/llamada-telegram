import ast
import io

def fix_file(filename):
    with io.open(filename, 'rb') as f:
        source = f.read()
    
    tree = ast.parse(source)
    globals_imported = set()
    for child in tree.body:
        if isinstance(child, ast.Import):
            for alias in child.names:
                globals_imported.add(alias.name.split('.')[0])
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                globals_imported.add((alias.asname or alias.name))
                
    lines_to_comment = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if alias.name.split('.')[0] in globals_imported:
                            lines_to_comment.add(child.lineno - 1)
                elif isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        if (alias.asname or alias.name) in globals_imported:
                            lines_to_comment.add(child.lineno - 1)
                            
    with io.open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for idx in sorted(list(lines_to_comment)):
        if not lines[idx].strip().startswith('#'):
            lines[idx] = '# ' + lines[idx]
            
    with io.open(filename, 'w', encoding='utf-8') as f:
        f.writelines(lines)

fix_file('bot_comandos.py')
fix_file('llamada.py')
