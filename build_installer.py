import os
import subprocess
import shutil

def build_dist():
    print("Starting build process...")
    
    # 1. Frontend Build
    print("Building frontend...")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    subprocess.run("npm run build", shell=True, cwd=frontend_dir, check=True)
    
    # 2. PyInstaller for Backend
    print("Compiling backend to executable...")
    backend_dir = os.path.join(os.getcwd(), "backend")
    # We use --onedir to keep it manageable and fast
    subprocess.run("venv\\Scripts\\pyinstaller --name engine --onefile engine.py", 
                   shell=True, cwd=backend_dir, check=True)
    
    # 3. Tauri Build (Native Installer)
    print("Building Tauri native installer...")
    subprocess.run("npm run tauri build", shell=True, cwd=frontend_dir, check=True)
    
    print("\nSuccess! Final installer located in: frontend/src-tauri/target/release/bundle/msi/")

if __name__ == "__main__":
    build_dist()
