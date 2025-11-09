# Basket2MD

Basket2MD is a Python script that migrates notes from KDE Basket to Obsidian while preserving the tree structure. It converts HTML notes to Markdown, copies attached files, and organizes everything into a hierarchical folder structure suitable for Obsidian.

## Installation

### Requirements
- Python 3.14 or higher (required for `pathlib.copy`)

### Setup
1. Clone the repository and navigate to the directory:
   ```bash
   git clone https://github.com/vozbu/basket2md.git
   cd basket2md
   ```
2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   ```
3. Activate the virtual environment:
   - On bash/zsh:
     ```bash
     source venv/bin/activate
     ```
   - On fish:
     ```bash
     source venv/bin/activate.fish
     ```
4. Install dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```

## Usage

Run the script with the following command:
```bash
./basket2md.py -o /path/to/obsidian/vault
```

### Options
- `-i, --input`: Path to KDE Basket directory (default: `~/.local/share/basket/baskets`)
- `-o, --output`: Path to Obsidian vault directory (required)
- `-v, --verbose`: Increase verbosity (use `-vv` for more details)

Example:
```bash
./basket2md.py -i ~/.local/share/basket/baskets -o ~/Documents/Obsidian/MyVault -vv
```

## Supported Features

### File Copying
- Copies attached files (images, documents, etc.) from Basket notes to the corresponding Obsidian folders
- Preserves file metadata during copying
- Handles missing files gracefully with warnings

### Note Types
- **HTML notes**: Converted to Markdown using the `markdownify` library
- **Text (.txt) files**: Converted to separate Markdown (.md) files with frontmatter metadata, instead of being copied as attachments
- **Links**: Converted to Markdown link format `[title](url)`
- **Images/Files**: Referenced files are copied to the output directory
- **Todo items**: Converted to Markdown checkboxes (`- [x]` for done, `- [ ]` for unchecked)
- **Titles**: Converted to Markdown headers (`# Title`)

### Note Groups
- Processes nested note groups from Basket's XML structure
- Maintains hierarchical organization in Obsidian
- Creates separate Markdown files for each Basket folder

### Frontmatter
Each generated Markdown file includes YAML frontmatter with metadata:
- `source`: Always set to "KDE Basket"
- `dir_name`: The original Basket directory name
- `created`: The earliest creation date (ISO format) from all notes in the group (if available)
- `updated`: The latest modification date (ISO format) from all notes in the group (if available)

### File and Directory Timestamps
The access time (atime) and modification time (mtime) of generated Markdown files and directories are set based on the collected dates:
- For files: Access time is set to the `created` date if available, otherwise to the `updated` date; modification time is set to the `updated` date if available
- For directories: Modification time is set to the latest `updated` date from all notes and subdirectories within that directory

## What could be better

### HTML formatting support

Basket has some formatting made weird, parsers don't handle it well.

### Titles detection

Subnotes sometimes has titles in it not structured as titles in HTML files. It could be extracted with some
kind of heuristics.
