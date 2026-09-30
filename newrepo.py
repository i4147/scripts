import subprocess as sp
import sys
from pathlib import Path
from typing import Tuple, Optional, Protocol, List, Type
from loguru import logger
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)


@dataclass
class BackendCapability:
    name: str
    available: bool
    error: Optional[str] = None


class GitBackendInterface(ABC):
    @abstractmethod
    def is_git_repo(self) -> bool: ...
    
    @abstractmethod
    def init_repo(self) -> None: ...
    
    @abstractmethod
    def copy_gitignore(self) -> None: ...
    
    @abstractmethod
    def handle_submodules(self) -> None: ...
    
    @abstractmethod
    def get_remote_url(self) -> Optional[str]: ...
    
    @abstractmethod
    def get_remote_owner(self, url: str) -> Optional[str]: ...
    
    @abstractmethod
    def get_current_user(self) -> Optional[str]: ...
    
    @abstractmethod
    def remove_remote(self) -> None: ...
    
    @abstractmethod
    def add_remote(self, url: str) -> None: ...
    
    @abstractmethod
    def create_github_repo(self, repo_name: str) -> str: ...
    
    @abstractmethod
    def add_all_files(self) -> None: ...
    
    @abstractmethod
    def has_changes(self) -> bool: ...
    
    @abstractmethod
    def commit(self, message: str) -> None: ...
    
    @abstractmethod
    def get_current_branch(self) -> str: ...
    
    @abstractmethod
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]: ...
    
    @abstractmethod
    def pull_rebase(self, branch: str) -> None: ...


class SubprocessGhBackend(GitBackendInterface):
    
    def __init__(self):
        self.repo_path: Path = Path.cwd()
        self.github_token: Optional[str] = self._load_github_token()
        if not self.github_token:
            raise RuntimeError("GITHUB_TOKEN not found in ~/.env")
        logger.info(f"[SubprocessGh] Initialized with repo: {self.repo_path.name}")
    
    def _load_github_token(self) -> Optional[str]:
        env_file: Path = Path.home() / '.env'
        if not env_file.exists():
            return None
        
        try:
            content: str = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('GITHUB_TOKEN='):
                    token: str = line.split('=', 1)[1].strip().strip('\'"')
                    return token if token else None
        except Exception as e:
            logger.warning(f"[SubprocessGh] Failed to read ~/.env: {e}")
        
        return None
    
    def run(self, cmd: List[str], check: bool = True) -> sp.CompletedProcess:
        logger.debug(f"[SubprocessGh] Running: {' '.join(cmd)}")
        env: dict = os.environ.copy()
        env['GITHUB_TOKEN'] = self.github_token
        
        result: sp.CompletedProcess = sp.run(
            cmd, capture_output=True, text=True, env=env
        )
        
        if check and result.returncode != 0:
            raise RuntimeError(f"[SubprocessGh] Command failed: {result.stderr}")
        
        return result
    
    def is_git_repo(self) -> bool:
        result: sp.CompletedProcess = self.run(
            ['git', 'rev-parse', '--git-dir'], check=False
        )
        return result.returncode == 0
    
    def init_repo(self) -> None:
        logger.info("[SubprocessGh] Initializing git repository...")
        self.run(['git', 'init'])
    
    def copy_gitignore(self) -> None:
        home_gitignore: Path = Path.home() / '.gitignore'
        local_gitignore: Path = self.repo_path / '.gitignore'
        
        if local_gitignore.exists():
            return
        
        if home_gitignore.exists():
            logger.info("[SubprocessGh] Copying .gitignore from home...")
            try:
                local_gitignore.write_text(home_gitignore.read_text())
            except Exception as e:
                logger.warning(f"[SubprocessGh] Failed to copy .gitignore: {e}")
    
    def handle_submodules(self) -> None:
        gitmodules: Path = self.repo_path / '.gitmodules'
        if not gitmodules.exists():
            return
        
        logger.info("[SubprocessGh] Initializing submodules...")
        self.run(['git', 'submodule', 'init'])
        logger.info("[SubprocessGh] Updating submodules recursively...")
        self.run(['git', 'submodule', 'update', '--init', '--recursive'])
    
    def get_remote_url(self) -> Optional[str]:
        result: sp.CompletedProcess = self.run(
            ['git', 'remote', 'get-url', 'origin'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None
    
    def get_remote_owner(self, url: str) -> Optional[str]:
        match: Optional[re.Match] = re.search(
            r'(?:github\.com[:/]|@github\.com:)([^/]+)', url
        )
        return match.group(1) if match else None
    
    def get_current_user(self) -> Optional[str]:
        result: sp.CompletedProcess = self.run(
            ['gh', 'auth', 'status', '-t'], check=False
        )
        if result.returncode == 0:
            match: Optional[re.Match] = re.search(r'as\s+(\S+)', result.stdout)
            return match.group(1) if match else None
        return None
    
    def remove_remote(self) -> None:
        logger.info("[SubprocessGh] Removing origin remote...")
        self.run(['git', 'remote', 'remove', 'origin'], check=False)
    
    def add_remote(self, url: str) -> None:
        logger.info(f"[SubprocessGh] Adding remote: {url}")
        self.run(['git', 'remote', 'add', 'origin', url])
    
    def create_github_repo(self, repo_name: str) -> str:
        logger.info(f"[SubprocessGh] Creating GitHub repository '{repo_name}'...")
        self.run(['gh', 'repo', 'create', repo_name, '--public', '--source=.'])
        
        result: sp.CompletedProcess = self.run(
            ['gh', 'repo', 'view', '--json', 'url', '-q', '.url'],
            check=False
        )
        if result.returncode == 0:
            url: str = result.stdout.strip()
            logger.info(f"[SubprocessGh] Created repo: {url}")
            return url
        
        current_user: Optional[str] = self.get_current_user()
        if current_user:
            url: str = f"git@github.com:{current_user}/{repo_name}.git"
            return url
        
        raise RuntimeError("[SubprocessGh] Failed to create GitHub repo")
    
    def add_all_files(self) -> None:
        logger.info("[SubprocessGh] Staging all files...")
        self.run(['git', 'add', '-A'])
    
    def has_changes(self) -> bool:
        result: sp.CompletedProcess = self.run(
            ['git', 'status', '--porcelain'], check=False
        )
        return bool(result.stdout.strip())
    
    def commit(self, message: str) -> None:
        logger.info(f"[SubprocessGh] Committing: {message}")
        self.run(['git', 'commit', '-m', message])
    
    def get_current_branch(self) -> str:
        result: sp.CompletedProcess = self.run(
            ['git', 'branch', '--show-current'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else 'main'
    
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        logger.info(f"[SubprocessGh] Pushing '{branch}' to origin...")
        result: sp.CompletedProcess = self.run(
            ['git', 'push', '--set-upstream', 'origin', branch],
            check=False
        )
        success: bool = result.returncode == 0
        error: Optional[str] = result.stderr if result.returncode != 0 else None
        return (success, error)
    
    def pull_rebase(self, branch: str) -> None:
        logger.info(f"[SubprocessGh] Pulling '{branch}' with rebase...")
        self.run(['git', 'pull', 'origin', branch, '--rebase'])


class GitPythonBackend(GitBackendInterface):
    
    def __init__(self):
        try:
            from git import Repo
            from git.exc import InvalidGitRepositoryError
            self.Repo = Repo
            self.InvalidGitRepositoryError = InvalidGitRepositoryError
        except ImportError as e:
            raise RuntimeError(f"[GitPython] Import failed: {e}")
        
        self.repo_path: Path = Path.cwd()
        self.github_token: Optional[str] = self._load_github_token()
        if not self.github_token:
            raise RuntimeError("[GitPython] GITHUB_TOKEN not found")
        
        logger.info(f"[GitPython] Initialized with repo: {self.repo_path.name}")
    
    def _load_github_token(self) -> Optional[str]:
        env_file: Path = Path.home() / '.env'
        if not env_file.exists():
            return None
        
        try:
            content: str = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('GITHUB_TOKEN='):
                    token: str = line.split('=', 1)[1].strip().strip('\'"')
                    return token if token else None
        except Exception as e:
            logger.warning(f"[GitPython] Failed to read ~/.env: {e}")
        
        return None
    
    def is_git_repo(self) -> bool:
        try:
            self.Repo(str(self.repo_path))
            return True
        except:
            return False
    
    def init_repo(self) -> None:
        logger.info("[GitPython] Initializing git repository...")
        self.Repo.init(str(self.repo_path))
    
    def copy_gitignore(self) -> None:
        home_gitignore: Path = Path.home() / '.gitignore'
        local_gitignore: Path = self.repo_path / '.gitignore'
        
        if local_gitignore.exists():
            return
        
        if home_gitignore.exists():
            logger.info("[GitPython] Copying .gitignore from home...")
            try:
                local_gitignore.write_text(home_gitignore.read_text())
            except Exception as e:
                logger.warning(f"[GitPython] Failed to copy .gitignore: {e}")
    
    def handle_submodules(self) -> None:
        gitmodules: Path = self.repo_path / '.gitmodules'
        if not gitmodules.exists():
            return
        
        try:
            repo: object = self.Repo(str(self.repo_path))
            logger.info("[GitPython] Initializing submodules...")
            repo.git.submodule('init')
            logger.info("[GitPython] Updating submodules recursively...")
            repo.git.submodule('update', '--init', '--recursive')
        except Exception as e:
            raise RuntimeError(f"[GitPython] Submodule handling failed: {e}")
    
    def get_remote_url(self) -> Optional[str]:
        try:
            repo: object = self.Repo(str(self.repo_path))
            if 'origin' in repo.remotes:
                return repo.remotes.origin.url
        except:
            pass
        return None
    
    def get_remote_owner(self, url: str) -> Optional[str]:
        match: Optional[re.Match] = re.search(
            r'(?:github\.com[:/]|@github\.com:)([^/]+)', url
        )
        return match.group(1) if match else None
    
    def get_current_user(self) -> Optional[str]:
        result: sp.CompletedProcess = sp.run(
            ['gh', 'auth', 'status', '-t'], capture_output=True, text=True
        )
        if result.returncode == 0:
            match: Optional[re.Match] = re.search(r'as\s+(\S+)', result.stdout)
            return match.group(1) if match else None
        return None
    
    def remove_remote(self) -> None:
        logger.info("[GitPython] Removing origin remote...")
        try:
            repo: object = self.Repo(str(self.repo_path))
            if 'origin' in repo.remotes:
                repo.delete_remote('origin')
        except Exception as e:
            raise RuntimeError(f"[GitPython] Failed to remove remote: {e}")
    
    def add_remote(self, url: str) -> None:
        logger.info(f"[GitPython] Adding remote: {url}")
        try:
            repo: object = self.Repo(str(self.repo_path))
            repo.create_remote('origin', url)
        except Exception as e:
            raise RuntimeError(f"[GitPython] Failed to add remote: {e}")
    
    def create_github_repo(self, repo_name: str) -> str:
        logger.info(f"[GitPython] Creating GitHub repository '{repo_name}'...")
        result: sp.CompletedProcess = sp.run(
            ['gh', 'repo', 'create', repo_name, '--public', '--source=.'],
            capture_output=True, text=True,
            env={**os.environ, 'GITHUB_TOKEN': self.github_token}
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"[GitPython] Failed to create repo: {result.stderr}")
        
        result = sp.run(
            ['gh', 'repo', 'view', '--json', 'url', '-q', '.url'],
            capture_output=True, text=True,
            env={**os.environ, 'GITHUB_TOKEN': self.github_token}
        )
        
        if result.returncode == 0:
            url: str = result.stdout.strip()
            logger.info(f"[GitPython] Created repo: {url}")
            return url
        
        current_user: Optional[str] = self.get_current_user()
        if current_user:
            url: str = f"git@github.com:{current_user}/{repo_name}.git"
            return url
        
        raise RuntimeError("[GitPython] Failed to create GitHub repo")
    
    def add_all_files(self) -> None:
        logger.info("[GitPython] Staging all files...")
        try:
            repo: object = self.Repo(str(self.repo_path))
            repo.index.add('*')
        except Exception as e:
            raise RuntimeError(f"[GitPython] Failed to stage files: {e}")
    
    def has_changes(self) -> bool:
        try:
            repo: object = self.Repo(str(self.repo_path))
            return bool(repo.index.diff(None))
        except:
            return False
    
    def commit(self, message: str) -> None:
        logger.info(f"[GitPython] Committing: {message}")
        try:
            repo: object = self.Repo(str(self.repo_path))
            repo.index.commit(message)
        except Exception as e:
            raise RuntimeError(f"[GitPython] Commit failed: {e}")
    
    def get_current_branch(self) -> str:
        try:
            repo: object = self.Repo(str(self.repo_path))
            return repo.active_branch.name
        except:
            return 'main'
    
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        logger.info(f"[GitPython] Pushing '{branch}' to origin...")
        try:
            repo: object = self.Repo(str(self.repo_path))
            repo.remotes.origin.push(branch)
            return (True, None)
        except Exception as e:
            return (False, str(e))
    
    def pull_rebase(self, branch: str) -> None:
        logger.info(f"[GitPython] Pulling '{branch}' with rebase...")
        try:
            repo: object = self.Repo(str(self.repo_path))
            repo.remotes.origin.pull(branch)
        except Exception as e:
            raise RuntimeError(f"[GitPython] Pull failed: {e}")


class PyGithubBackend(GitBackendInterface):
    
    def __init__(self):
        try:
            from github import Github
            self.Github = Github
        except ImportError as e:
            raise RuntimeError(f"[PyGithub] Import failed: {e}")
        
        self.repo_path: Path = Path.cwd()
        self.github_token: Optional[str] = self._load_github_token()
        if not self.github_token:
            raise RuntimeError("[PyGithub] GITHUB_TOKEN not found")
        
        self.gh_client: object = self.Github(self.github_token)
        logger.info(f"[PyGithub] Initialized with repo: {self.repo_path.name}")
    
    def _load_github_token(self) -> Optional[str]:
        env_file: Path = Path.home() / '.env'
        if not env_file.exists():
            return None
        
        try:
            content: str = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('GITHUB_TOKEN='):
                    token: str = line.split('=', 1)[1].strip().strip('\'"')
                    return token if token else None
        except Exception as e:
            logger.warning(f"[PyGithub] Failed to read ~/.env: {e}")
        
        return None
    
    def run(self, cmd: List[str], check: bool = True) -> sp.CompletedProcess:
        logger.debug(f"[PyGithub] Running: {' '.join(cmd)}")
        env: dict = os.environ.copy()
        env['GITHUB_TOKEN'] = self.github_token
        
        result: sp.CompletedProcess = sp.run(
            cmd, capture_output=True, text=True, env=env
        )
        
        if check and result.returncode != 0:
            raise RuntimeError(f"[PyGithub] Command failed: {result.stderr}")
        
        return result
    
    def is_git_repo(self) -> bool:
        result: sp.CompletedProcess = self.run(
            ['git', 'rev-parse', '--git-dir'], check=False
        )
        return result.returncode == 0
    
    def init_repo(self) -> None:
        logger.info("[PyGithub] Initializing git repository...")
        self.run(['git', 'init'])
    
    def copy_gitignore(self) -> None:
        home_gitignore: Path = Path.home() / '.gitignore'
        local_gitignore: Path = self.repo_path / '.gitignore'
        
        if local_gitignore.exists():
            return
        
        if home_gitignore.exists():
            logger.info("[PyGithub] Copying .gitignore from home...")
            try:
                local_gitignore.write_text(home_gitignore.read_text())
            except Exception as e:
                logger.warning(f"[PyGithub] Failed to copy .gitignore: {e}")
    
    def handle_submodules(self) -> None:
        gitmodules: Path = self.repo_path / '.gitmodules'
        if not gitmodules.exists():
            return
        
        logger.info("[PyGithub] Initializing submodules...")
        self.run(['git', 'submodule', 'init'])
        logger.info("[PyGithub] Updating submodules recursively...")
        self.run(['git', 'submodule', 'update', '--init', '--recursive'])
    
    def get_remote_url(self) -> Optional[str]:
        result: sp.CompletedProcess = self.run(
            ['git', 'remote', 'get-url', 'origin'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None
    
    def get_remote_owner(self, url: str) -> Optional[str]:
        match: Optional[re.Match] = re.search(
            r'(?:github\.com[:/]|@github\.com:)([^/]+)', url
        )
        return match.group(1) if match else None
    
    def get_current_user(self) -> Optional[str]:
        try:
            user: object = self.gh_client.get_user()
            return user.login
        except:
            return None
    
    def remove_remote(self) -> None:
        logger.info("[PyGithub] Removing origin remote...")
        self.run(['git', 'remote', 'remove', 'origin'], check=False)
    
    def add_remote(self, url: str) -> None:
        logger.info(f"[PyGithub] Adding remote: {url}")
        self.run(['git', 'remote', 'add', 'origin', url])
    
    def create_github_repo(self, repo_name: str) -> str:
        logger.info(f"[PyGithub] Creating GitHub repository '{repo_name}'...")
        try:
            user: object = self.gh_client.get_user()
            repo: object = user.create_repo(repo_name, public=True)
            url: str = repo.clone_url
            logger.info(f"[PyGithub] Created repo: {url}")
            return url
        except Exception as e:
            raise RuntimeError(f"[PyGithub] Failed to create repo: {e}")
    
    def add_all_files(self) -> None:
        logger.info("[PyGithub] Staging all files...")
        self.run(['git', 'add', '-A'])
    
    def has_changes(self) -> bool:
        result: sp.CompletedProcess = self.run(
            ['git', 'status', '--porcelain'], check=False
        )
        return bool(result.stdout.strip())
    
    def commit(self, message: str) -> None:
        logger.info(f"[PyGithub] Committing: {message}")
        self.run(['git', 'commit', '-m', message])
    
    def get_current_branch(self) -> str:
        result: sp.CompletedProcess = self.run(
            ['git', 'branch', '--show-current'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else 'main'
    
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        logger.info(f"[PyGithub] Pushing '{branch}' to origin...")
        result: sp.CompletedProcess = self.run(
            ['git', 'push', '--set-upstream', 'origin', branch],
            check=False
        )
        success: bool = result.returncode == 0
        error: Optional[str] = result.stderr if result.returncode != 0 else None
        return (success, error)
    
    def pull_rebase(self, branch: str) -> None:
        logger.info(f"[PyGithub] Pulling '{branch}' with rebase...")
        self.run(['git', 'pull', 'origin', branch, '--rebase'])


class DulwichBackend(GitBackendInterface):
    
    def __init__(self):
        try:
            from dulwich.repo import Repo as DulwichRepo
            self.DulwichRepo = DulwichRepo
        except ImportError as e:
            raise RuntimeError(f"[Dulwich] Import failed: {e}")
        
        self.repo_path: Path = Path.cwd()
        self.github_token: Optional[str] = self._load_github_token()
        if not self.github_token:
            raise RuntimeError("[Dulwich] GITHUB_TOKEN not found")
        
        logger.info(f"[Dulwich] Initialized with repo: {self.repo_path.name}")
    
    def _load_github_token(self) -> Optional[str]:
        env_file: Path = Path.home() / '.env'
        if not env_file.exists():
            return None
        
        try:
            content: str = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('GITHUB_TOKEN='):
                    token: str = line.split('=', 1)[1].strip().strip('\'"')
                    return token if token else None
        except Exception as e:
            logger.warning(f"[Dulwich] Failed to read ~/.env: {e}")
        
        return None
    
    def run(self, cmd: List[str], check: bool = True) -> sp.CompletedProcess:
        logger.debug(f"[Dulwich] Running: {' '.join(cmd)}")
        env: dict = os.environ.copy()
        env['GITHUB_TOKEN'] = self.github_token
        
        result: sp.CompletedProcess = sp.run(
            cmd, capture_output=True, text=True, env=env
        )
        
        if check and result.returncode != 0:
            raise RuntimeError(f"[Dulwich] Command failed: {result.stderr}")
        
        return result
    
    def is_git_repo(self) -> bool:
        try:
            self.DulwichRepo(str(self.repo_path))
            return True
        except:
            return False
    
    def init_repo(self) -> None:
        logger.info("[Dulwich] Initializing git repository...")
        self.DulwichRepo.init(str(self.repo_path))
    
    def copy_gitignore(self) -> None:
        home_gitignore: Path = Path.home() / '.gitignore'
        local_gitignore: Path = self.repo_path / '.gitignore'
        
        if local_gitignore.exists():
            return
        
        if home_gitignore.exists():
            logger.info("[Dulwich] Copying .gitignore from home...")
            try:
                local_gitignore.write_text(home_gitignore.read_text())
            except Exception as e:
                logger.warning(f"[Dulwich] Failed to copy .gitignore: {e}")
    
    def handle_submodules(self) -> None:
        gitmodules: Path = self.repo_path / '.gitmodules'
        if not gitmodules.exists():
            return
        
        logger.info("[Dulwich] Initializing submodules...")
        self.run(['git', 'submodule', 'init'])
        logger.info("[Dulwich] Updating submodules recursively...")
        self.run(['git', 'submodule', 'update', '--init', '--recursive'])
    
    def get_remote_url(self) -> Optional[str]:
        result: sp.CompletedProcess = self.run(
            ['git', 'remote', 'get-url', 'origin'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None
    
    def get_remote_owner(self, url: str) -> Optional[str]:
        match: Optional[re.Match] = re.search(
            r'(?:github\.com[:/]|@github\.com:)([^/]+)', url
        )
        return match.group(1) if match else None
    
    def get_current_user(self) -> Optional[str]:
        result: sp.CompletedProcess = sp.run(
            ['gh', 'auth', 'status', '-t'], capture_output=True, text=True
        )
        if result.returncode == 0:
            match: Optional[re.Match] = re.search(r'as\s+(\S+)', result.stdout)
            return match.group(1) if match else None
        return None
    
    def remove_remote(self) -> None:
        logger.info("[Dulwich] Removing origin remote...")
        self.run(['git', 'remote', 'remove', 'origin'], check=False)
    
    def add_remote(self, url: str) -> None:
        logger.info(f"[Dulwich] Adding remote: {url}")
        self.run(['git', 'remote', 'add', 'origin', url])
    
    def create_github_repo(self, repo_name: str) -> str:
        logger.info(f"[Dulwich] Creating GitHub repository '{repo_name}'...")
        result: sp.CompletedProcess = self.run(
            ['gh', 'repo', 'create', repo_name, '--public', '--source=.'],
            check=False
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"[Dulwich] Failed to create repo: {result.stderr}")
        
        result = self.run(
            ['gh', 'repo', 'view', '--json', 'url', '-q', '.url'],
            check=False
        )
        
        if result.returncode == 0:
            url: str = result.stdout.strip()
            logger.info(f"[Dulwich] Created repo: {url}")
            return url
        
        current_user: Optional[str] = self.get_current_user()
        if current_user:
            url: str = f"git@github.com:{current_user}/{repo_name}.git"
            return url
        
        raise RuntimeError("[Dulwich] Failed to create GitHub repo")
    
    def add_all_files(self) -> None:
        logger.info("[Dulwich] Staging all files...")
        self.run(['git', 'add', '-A'])
    
    def has_changes(self) -> bool:
        result: sp.CompletedProcess = self.run(
            ['git', 'status', '--porcelain'], check=False
        )
        return bool(result.stdout.strip())
    
    def commit(self, message: str) -> None:
        logger.info(f"[Dulwich] Committing: {message}")
        self.run(['git', 'commit', '-m', message])
    
    def get_current_branch(self) -> str:
        result: sp.CompletedProcess = self.run(
            ['git', 'branch', '--show-current'], check=False
        )
        return result.stdout.strip() if result.returncode == 0 else 'main'
    
    def push_upstream(self, branch: str) -> Tuple[bool, Optional[str]]:
        logger.info(f"[Dulwich] Pushing '{branch}' to origin...")
        result: sp.CompletedProcess = self.run(
            ['git', 'push', '--set-upstream', 'origin', branch],
            check=False
        )
        success: bool = result.returncode == 0
        error: Optional[str] = result.stderr if result.returncode != 0 else None
        return (success, error)
    
    def pull_rebase(self, branch: str) -> None:
        logger.info(f"[Dulwich] Pulling '{branch}' with rebase...")
        self.run(['git', 'pull', 'origin', branch, '--rebase'])


class BackendOrchestrator:
    
    def __init__(self):
        self.backends: List[Type[GitBackendInterface]] = [
            SubprocessGhBackend,
            GitPythonBackend,
            PyGithubBackend,
            DulwichBackend,
        ]
        self.active_backend: Optional[GitBackendInterface] = None
        self.failed_backends: List[str] = []
    
    def initialize(self) -> GitBackendInterface:
        for backend_class in self.backends:
            try:
                backend_name: str = backend_class.__name__
                logger.info(f"Attempting to initialize {backend_name}...")
                self.active_backend = backend_class()
                logger.info(f"Successfully initialized {backend_name}")
                return self.active_backend
            except Exception as e:
                
