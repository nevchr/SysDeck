SysDeck

SysDeck is a Windows desktop utility built with Python and PySide6 for monitoring system activity, searching indexed files, analyzing storage, finding duplicate files, and organizing folders from one clean interface.



Features

Dashboard — quick overview of CPU, memory, process count, uptime, storage, and SysDeck index statistics.

Performance — live CPU, memory, disk, network, uptime, and process activity with lightweight history graphs.

Processes — searchable and sortable view of running Windows processes with CPU and memory usage.

Storage — analyze drives and folders, inspect space usage, and surface large files.

Indexed Search — build a local metadata index and quickly search files by name or path with filters for location, type, size, and modified date.

Duplicate Finder — detect exact duplicate files using staged hashing and safely move selected copies to the Windows Recycle Bin.

Organizer — preview and organize loose files into categories without overwriting existing files.

Index Management — reindex, remove, or clear indexed locations from Settings.

Local App Settings — optional last-page restore and local application data management.

Screenshots

Performance

Duplicate Finder





Settings

Dashboard





Install

SysDeck v1.0.0 is distributed as a Windows installer.

Open the repository's Releases page.

Download SysDeck-Setup-1.0.0.exe.

Run the installer.

Launch SysDeck from the Start Menu.

Note: The current installer is not code-signed, so Windows SmartScreen may show an "Unknown publisher" warning.

System requirements

Windows 10 or Windows 11

64-bit Windows

How SysDeck handles your files

SysDeck is designed to keep destructive actions explicit and limited:

The search index stores file metadata, not file contents.

Indexed data is stored locally in SQLite.

Duplicate cleanup sends files to the Windows Recycle Bin rather than permanently deleting them.

Organizer moves are previewed before execution and do not overwrite existing files.

Removing a location from the index does not delete the actual folder or its files.

Application data is stored under:

%LOCALAPPDATA%\SysDeck\

Run from source

1. Clone the repository

git clone https://github.com/nevchr/SysDeck.git
cd SysDeck

2. Create and activate a virtual environment

python -m venv .venv
.\.venv\Scripts\Activate.ps1

3. Install dependencies

python -m pip install -r requirements.txt

4. Run SysDeck

python -m src.sysdeck.main

Build the Windows executable

Install PyInstaller:

python -m pip install pyinstaller

Build the application:

pyinstaller --noconfirm --clean --windowed --name SysDeck --icon "assets\sysdeck_icon.ico" --add-data "assets;assets" run_sysdeck.py

The onedir build will be created under:

dist\SysDeck\

Build the installer

SysDeck uses Inno Setup for the installer.

Compile:

installer\SysDeck.iss

The installer is written to:

installer-output\SysDeck-Setup-1.0.0.exe

Tech stack

Python

PySide6 / Qt

psutil

SQLite

Send2Trash

PyInstaller

Inno Setup

Git / GitHub

Project structure

SysDeck/
├── assets/
├── installer/
├── src/
│   └── sysdeck/
│       ├── core/
│       └── ui/
├── run_sysdeck.py
├── requirements.txt
└── README.md

Version

SysDeck v1.0.0

Initial release focused on a polished, local-first Windows system utility with system monitoring, file indexing/search, storage analysis, duplicate detection, and file organization.

License

No license has been added yet. All rights are reserved unless a license is added to the repository.