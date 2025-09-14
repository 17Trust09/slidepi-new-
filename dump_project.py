import os

# Verzeichnis des Skripts als Projekt-Root setzen
project_root = os.path.dirname(os.path.abspath(__file__))

output_file = os.path.join(project_root, "slidepi_dump.txt")

with open(output_file, "w", encoding="utf-8") as out:
    out.write("### Projektstruktur ###\n\n")

    # Projektstruktur (ohne venv) darstellen
    for root, dirs, files in os.walk(project_root):
        # venv-Verzeichnisse überspringen
        dirs[:] = [d for d in dirs if d != ".venv"]

        # relativen Pfad ab Projekt-Root berechnen
        rel_path = os.path.relpath(root, project_root)
        indent_level = rel_path.count(os.sep)
        indent = "    " * indent_level

        if rel_path == ".":
            out.write(f"{os.path.basename(project_root)}/\n")
        else:
            out.write(f"{indent}{os.path.basename(root)}/\n")

        for file in sorted(files):
            out.write(f"{indent}    {file}\n")

    out.write("\n\n### Dateiinhalte ###\n\n")

    # Inhalte aller relevanten Dateien anhängen
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d != "venv"]

        for file in files:
            if file.endswith((".py", ".html")):
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, project_root)
                out.write(f"===== {rel_path} =====\n")
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        out.write(f.read())
                except Exception as e:
                    out.write(f"!!! Fehler beim Lesen: {e}\n")
                out.write("\n\n")

print(f"Dump erstellt: {output_file}")
