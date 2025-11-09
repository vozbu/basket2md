#!/usr/bin/env python3
"""
Script for migrating notes from KDE Basket to Obsidian while preserving the tree structure.

Terminology:
- dir: a directory on a file system
- folder: a folder in an application
- note tree: a tree of note folders in an application

For Obsidian note tree maps one-to-one to dirs on the file system, while in Basket there is a difference.

In Basket there is a root dir containing other dirs (called 'basketN', where N is a changing number)
in a flat list with notes at one level inside them.
In this root dir there is an index file called `baskets.xml` which reflects the note tree structure,
showing how the aforementioned flat dirs on the file system map to the note tree in the application.
In each 'basketN' dir there is an XML file called '.basket' which describes notes in this dir.

.local/share/basket/baskets
    baskets.xml
    basket1
        .basket
        note1.txt
        note2.html
        file1.img
    basket2
        .basket
        note3.html
        file2.xlsx
    ...
"""

import argparse
# import json
import logging
import markdownify
from bs4 import BeautifulSoup
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime
import os


LOG_LEVEL_NOTICE = 25


def get_basket_directory(custom_path=None):
    """Get path to KDE Basket directory."""
    if custom_path:
        path = Path(custom_path)
    else:
        path = Path.home() / '.local' / 'share' / 'basket' / 'baskets'

    if not path.exists():
        logging.error(f"❌ KDE Basket directory '{path}' not found!")
        return None

    return path


def get_obsidian_vault(custom_path):
    """Get path to Obsidian vault."""
    path = Path(custom_path)

    if not path.exists():
        logging.error(f"❌ Obsidian path '{path}' does not exist")
        return None

    return path


class BasketItem:
    """Class representing a Basket item (folder)."""

    def __init__(self, folder, dir):
        self.folder = folder    # basket name in the application
        self.dir = dir          # dir name in Basket file system (only one level relative to root)
        self.children = []      # nested baskets (BasketItem elements)

    def to_dict(self):
        res = {"folder": self.folder,
               "dir": self.dir,
               "children": [],
               }
        for c in self.children:
            res["children"].append(c.to_dict())
        return res


def parse_baskets_structure(basket_path):
    """Parse baskets.xml to build tree structure."""
    baskets_xml = basket_path / 'baskets.xml'
    if not baskets_xml.exists():
        logging.error("❌ File baskets.xml not found!")
        return None

    try:
        tree = ET.parse(baskets_xml)
        root = tree.getroot()

        # Create root folder
        root_basket = BasketItem("Basket-Import", None)

        def parse_basket_element(element, parent_basket):
            """Recursive parsing of basket elements."""
            for child in element:
                if child.tag == 'basket':
                    # Get folder path in file system (actually we call it 'dir')
                    folder_name = child.get('folderName', '')

                    # Get folder name in application from properties/name
                    display_name = folder_name  # by default use folderName
                    properties = child.find('properties')
                    if properties is not None:
                        name_elem = properties.find('name')
                        if name_elem is not None and name_elem.text:
                            display_name = name_elem.text

                    if not display_name:
                        display_name = "Unnamed Basket"

                    # Create folder element
                    basket_item = BasketItem(display_name, folder_name)
                    parent_basket.children.append(basket_item)

                    # Recursively parse nested elements
                    parse_basket_element(child, basket_item)

        # Start parsing from root element
        parse_basket_element(root, root_basket)

        logging.info(f"✅ Basket structure successfully parsed")
        return root_basket

    except Exception as e:
        logging.error(f"❌ Error parsing baskets.xml: {e}")
        return None


# dir_path - path to subfolder in basket folder on FS.
# basket_xml_file - file dir_path/.basket
# xml_node - current group in basket_xml_file
# obsidian_folder_path - path within obsidian tree to this folder.
def process_notes_group(dir_path, basket_xml_file, xml_node, obsidian_folder_path, stats):
    """ Processes group of notes found in tag 'group' inside of basketN/.basket file. """

    markdown_content = ""
    min_added = None
    max_lastmod = None
    files_copied = 0

    for child in xml_node:
        if child.tag == 'note':
            type = child.get('type', '')

            content_tag = child.find("content")
            if (content_tag is None):
                logging.warning(f"⚠️  'content' tag not found in file '{basket_xml_file}'!")
                continue

            added_str = child.get('added')
            if added_str:
                try:
                    added_dt = datetime.fromisoformat(added_str)
                    min_added = min(min_added, added_dt) if min_added else added_dt
                except ValueError:
                    logging.warning(f"⚠️ Invalid 'added' date '{added_str}' in {basket_xml_file}")

            lastmod_str = child.get('lastModification')
            if lastmod_str:
                try:
                    lastmod_dt = datetime.fromisoformat(lastmod_str)
                    max_lastmod = max(max_lastmod, lastmod_dt) if max_lastmod else lastmod_dt
                except ValueError:
                    logging.warning(f"⚠️ Invalid 'lastModification' date '{lastmod_str}' in {basket_xml_file}")

            match type:
                case 'html':
                    None  # handle it later

                case 'link':
                    title = content_tag.get('title', 'link')
                    markdown_content += f"[{title}]({content_tag.text})\n"
                    continue

                case 'image' | 'file':
                    note_file_path = dir_path / content_tag.text
                    if note_file_path.exists():
                        obsidian_folder_path.mkdir(exist_ok=True)
                        note_file_path.copy(obsidian_folder_path / content_tag.text, preserve_metadata=True)
                        stats['files_copied'][note_file_path.suffix.lower()] += 1
                        files_copied += 1
                    else:
                        logging.warning(f"⚠️  file '{note_file_path}' doesn't exist")
                    continue

                case _:
                    logging.warning(f"⚠️  skipped unknown content type '{type}' in file '{basket_xml_file}'")
                    continue

            note_file_path = dir_path / content_tag.text

            title, html_content = parse_html_note(note_file_path)
            converted_content = convert_html_to_markdown(html_content)
            if not converted_content:
                converted_content += "*Empty note*\n\n"

            tags = child.find("tags")
            if tags is not None:
                for tag in tags.text.split(';'):
                    match tag:
                        case "todo_done":
                            markdown_content += "- [x] "
                        case "todo_unchecked":
                            markdown_content += "- [ ] "
                        case "title":
                            markdown_content += "# " + converted_content + "\n\n"
                        case None:
                            markdown_content += f"# {title}\n\n"
                        case _:
                            logging.warning(f"⚠️  Unknown tag '{tag}' from tags '{tags.text}' in file '{basket_xml_file}'!")

            if converted_content and tags is None or tags.text != "title":
                markdown_content += f"{converted_content}\n"

            stats['notes_processed'] += 1

        elif child.tag == 'group':
            sub_content, sub_min, sub_max, sub_files = process_notes_group(dir_path, basket_xml_file, child, obsidian_folder_path, stats)
            markdown_content += sub_content + '\n'
            files_copied += sub_files
            if sub_min is not None:
                min_added = min(min_added, sub_min) if min_added else sub_min
            if sub_max is not None:
                max_lastmod = max(max_lastmod, sub_max) if max_lastmod else sub_max

        else:
            logging.warning(f"⚠️  Unknown tag '{child.tag}' in file '{basket_xml_file}'!")

    return markdown_content, min_added, max_lastmod, files_copied


# basket_path - path to basket folder on FS.
# dir_name - name of subfolder in basket folder on FS.
# obsidian_folder_path - path within obsidian tree to this folder.
def read_and_format_notes(basket_path, dir_name, obsidian_folder_path, stats):
    """Find all notes in specified Basket dir and renders them into one markdown file."""

    # markdown_content, min_added, max_lastmod, files_copied
    default_return = "", None, None, 0

    if dir_name is None:
        return default_return

    dir_name = dir_name.rstrip('/')

    if not dir_name:
        return default_return

    dir_path = basket_path / dir_name
    if not dir_path.exists():
        print(f"⚠️ Folder not found: {dir_name}")
        return default_return

    basket_xml = dir_path / '.basket'
    if not basket_xml.exists():
        print(f"⚠️  File {basket_xml} not found!")
        return default_return

    tree = ET.parse(basket_xml)
    root = tree.getroot()
    xml_notes = root.find('notes')
    if (xml_notes is None):
        print(f"⚠️  File {basket_xml} does not contain '<notes>' tag!")
        return default_return

    content, min_added, max_lastmod, files_copied = process_notes_group(dir_path, basket_xml, xml_notes, obsidian_folder_path, stats)

    frontmatter = f"""---
source: KDE Basket
dir_name: {dir_name}
"""
    if min_added is not None:
        frontmatter += f"created: {min_added.isoformat()}\n"
    if max_lastmod is not None:
        frontmatter += f"updated: {max_lastmod.isoformat()}\n"
    frontmatter += "---\n\n"

    markdown_content = frontmatter + content

    return markdown_content, min_added, max_lastmod, files_copied


def parse_html_note(html_file_path):
    """Parse HTML file with note."""
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'html.parser')

        # Extract title from <title> tag or file name
        title_tag = soup.find('title')
        if title_tag and title_tag.get_text().strip():
            title = title_tag.get_text().strip()
        else:
            title = html_file_path.stem

        # Extract note body
        body_tag = soup.find('body')
        if body_tag:
            body_content = body_tag.decode_contents()
        else:
            body_content = content

        return title, body_content

    except Exception as e:
        print(f"⚠️ Error reading {html_file_path}: {e}")
        return html_file_path.stem, ""


def convert_html_to_markdown(text):
    return markdownify.markdownify(text)
    # return html2markdown.convert(text)


def sanitize_filename(name):
    """Create safe filename."""
    if not name:
        return "Unnamed"

    # Remove invalid characters in filenames
    invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
    sanitized = name
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')

    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip('. ')

    # Limit name length
    if len(sanitized) > 100:
        sanitized = sanitized[:100]

    return sanitized


def write_note(content, filename, created=None, updated=None):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    if updated or created:
        atime = created.timestamp() if created else updated.timestamp()
        mtime = updated.timestamp() if updated else atime
        os.utime(filename, (atime, mtime))
    logging.info(f"  ✅ Created file: {filename}")


def process_basket_item(basket_item, basket_path, current_obsidian_path, stats):
    """Recursive processing of Basket item."""

    # If item has nested baskets or files to copy, then:
    # - Create a folder for this item
    # - All notes of this item go into file <folder_name>.md in that folder
    # - For each child create a subfolder and process recursively there.
    # If no children and no files, then:
    # - Don't create folder for this item, create note in parent root with item name,
    #   and put all found notes of this item there.

    logging.info(f"📂 Processing folder: {basket_item.folder}")

    folder_path = current_obsidian_path
    safe_name = sanitize_filename(basket_item.folder)

    # Format notes in this Basket folder into one document
    notes_before = stats["notes_processed"]
    obsidian_folder_path = folder_path / safe_name
    content, min_added, max_lastmod, files_copied = read_and_format_notes(basket_path, basket_item.dir, obsidian_folder_path, stats)
    notes_after = stats["notes_processed"]
    found_notes = notes_after - notes_before
    logging.info(f"  📄 Notes found: {found_notes}")
    if (files_copied > 0):
        logging.info(f"  📁 Files copied: {files_copied}")

    create_folder = len(basket_item.children) > 0 or files_copied > 0
    max_child_updated = None
    if create_folder:
        # Create folder in Obsidian
        folder_path = obsidian_folder_path
        folder_path.mkdir(exist_ok=True)
        stats['folders_created'] += 1

        # Recursively process nested baskets
        for child in basket_item.children:
            child_max = process_basket_item(child, basket_path, folder_path, stats)
            if child_max:
                max_child_updated = max(max_child_updated, child_max) if max_child_updated else child_max

    # Write notes of this folder to folder_path
    if found_notes > 0:
        mdfile = folder_path / f"{safe_name}.md"
        write_note(content, mdfile, created=min_added, updated=max_lastmod)

    overall_max = max_lastmod
    if max_child_updated:
        overall_max = max(overall_max, max_child_updated) if overall_max else max_child_updated

    if create_folder and overall_max:
        os.utime(folder_path, (os.path.getatime(folder_path), overall_max.timestamp()))

    return overall_max


def process_basket_structure(basket_path, obsidian_path):
    """Process entire Basket structure."""

    # Parse structure from baskets.xml
    root_basket = parse_baskets_structure(basket_path)
    if not root_basket:
        return 0, 0

    stats = {
        'folders_created': 0,
        'notes_processed': 0,
        'files_copied': defaultdict(int)
    }

    logging.info("🔄 Starting structure creation...")

    # Process root folder and all nested ones
    process_basket_item(root_basket, basket_path, obsidian_path, stats)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate KDE Basket to Obsidian structure")
    parser.add_argument("-i", "--input", help="Path to KDE Basket directory (default: ~/.local/share/basket/baskets)")
    parser.add_argument("-o", "--output", required=True, help="Path to Obsidian vault directory")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (use -vv for more details)")
    args = parser.parse_args()

    # Configure logging based on verbosity level
    if args.verbose >= 2:
        logging.basicConfig(level=logging.INFO, format='%(message)s')
    elif args.verbose >= 1:
        logging.basicConfig(level=LOG_LEVEL_NOTICE, format='%(message)s')
    else:
        logging.basicConfig(level=logging.WARNING, format='%(message)s')

    logging.log(LOG_LEVEL_NOTICE, "🚀 Starting KDE Basket to Obsidian structure migration")
    logging.log(LOG_LEVEL_NOTICE, "📂 Each Basket folder → one Obsidian note")
    logging.log(LOG_LEVEL_NOTICE, "=" * 50)

    # Get paths
    basket_path = get_basket_directory(args.input)
    if not basket_path:
        return

    obsidian_path = get_obsidian_vault(args.output)
    if not obsidian_path:
        return

    logging.log(LOG_LEVEL_NOTICE, f"📁 Basket directory: {basket_path}")
    logging.log(LOG_LEVEL_NOTICE, f"📁 Obsidian vault: {obsidian_path}")
    logging.log(LOG_LEVEL_NOTICE, "")

    # root_basket = parse_baskets_structure(basket_path)
    # print(json.dumps(root_basket.to_dict(), indent=2, ensure_ascii=False))
    # return

    # Perform import
    stats = process_basket_structure(basket_path, obsidian_path)

    folders_created = stats['folders_created']
    notes_processed = stats['notes_processed']
    total_files = sum(stats['files_copied'].values())

    logging.log(LOG_LEVEL_NOTICE, "")
    logging.log(LOG_LEVEL_NOTICE, "=" * 50)
    logging.log(LOG_LEVEL_NOTICE, "📊 Import results:")
    logging.log(LOG_LEVEL_NOTICE, f"✅ Folders-notes created: {folders_created}")
    logging.log(LOG_LEVEL_NOTICE, f"✅ Nested notes processed: {notes_processed}")
    logging.log(LOG_LEVEL_NOTICE, f"✅ Files copied: {total_files}")

    for ext, count in sorted(stats['files_copied'].items(), key=lambda x: x[1], reverse=True):
        logging.log(LOG_LEVEL_NOTICE, f"  {ext}: {count}")

    if folders_created > 0:
        import_dir = obsidian_path / 'Basket-Import'
        logging.info(f"📁 Structure saved to: {import_dir}")
        logging.info("💡 Each Basket folder became a separate note in Obsidian")
        logging.info("💡 Nested notes included as sections in parent folders")


if __name__ == "__main__":
    main()
