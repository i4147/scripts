import ast
import argparse


class ImportRemover(ast.NodeTransformer):
    def __init__(self, unused_imports):
        self.unused_imports = unused_imports

    def visit_Import(self, node):
        
        new_names = [n for n in node.names if n.name not in self.unused_imports]
        if not new_names:
            return None  
        node.names = new_names
        return node

    def visit_ImportFrom(self, node):
        
        new_names = [n for n in node.names if n.name not in self.unused_imports]
        if not new_names:
            return None
        node.names = new_names
        return node


def get_unused_imports(file_path):
    with open(file_path, "r") as f:
        tree = ast.parse(f.read())

    imported_names = {}
    used_names = set()

    
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = node

        
        elif isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            
            if isinstance(node.value, ast.Name):
                used_names.add(node.value.id)

    
    unused = {name for name in imported_names if name not in used_names}
    return tree, unused


def clean_file(input_file, output_file):
    tree, unused = get_unused_imports(input_file)

    if not unused:
        print("No unused imports found.")
        return

    print(f"Removing: {', '.join(unused)}")

    
    transformer = ImportRemover(unused)
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)

    
    with open(output_file, "w") as f:
        f.write(ast.unparse(new_tree))
    print(f"Cleaned code written to `{output_file}`")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Python file to clean")
    args = parser.parse_args()

    clean_file(args.file, args.file)
