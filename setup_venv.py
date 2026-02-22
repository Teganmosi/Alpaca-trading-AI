#!/usr/bin/env python3
"""
Setup script to create and configure a Python virtual environment.
This script creates a virtual environment and provides activation instructions.
"""

import os
import sys
import subprocess
from pathlib import Path


def create_virtual_environment():
    """Create a Python virtual environment."""
    print("Creating virtual environment...")
    
    # Check if venv module is available
    try:
        import venv
    except ImportError:
        print("Error: venv module is not available.")
        print("Please install Python with the venv module.")
        return False
    
    # Create virtual environment
    try:
        venv.create("venv", with_pip=True)
        print("✓ Virtual environment created successfully!")
        return True
    except Exception as e:
        print(f"Error creating virtual environment: {e}")
        return False


def show_activation_instructions():
    """Show instructions for activating the virtual environment."""
    print("\n" + "="*60)
    print("Virtual Environment Setup Complete!")
    print("="*60)
    print("\nTo activate the virtual environment, use one of the following commands:")
    print("\nWindows:")
    print("  venv\\Scripts\\activate")
    print("\nmacOS/Linux:")
    print("  source venv/bin/activate")
    print("\nAfter activation, your prompt will change to show (venv).")
    print("\nTo deactivate the virtual environment, run:")
    print("  deactivate")
    print("\n" + "="*60)


def main():
    """Main execution function."""
    print("Python Virtual Environment Setup")
    print("="*60)
    
    # Check Python version
    print(f"\nPython version: {sys.version}")
    
    # Create virtual environment
    if create_virtual_environment():
        show_activation_instructions()
        
        # Optional: Install common packages
        print("\nWould you like to install common packages? (y/n)")
        choice = input("> ").strip().lower()
        if choice == 'y':
            print("\nInstalling common packages...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                             check=True, capture_output=True)
                print("✓ Packages installed successfully!")
            except FileNotFoundError:
                print("Note: requirements.txt not found. Skipping package installation.")
            except subprocess.CalledProcessError as e:
                print(f"Error installing packages: {e}")
    
    print("\nSetup complete!")


if __name__ == "__main__":
    main()
