import os
import yaml
import traceback

from shutil import copyfile, copy
from subprocess import run, PIPE, STDOUT, CalledProcessError

from foliant.utils import spinner
from foliant.backends.base import BaseBackend
from distutils.dir_util import copy_tree, remove_tree

SLATE_REPO = 'https://github.com/lord/slate.git'


class Backend(BaseBackend):
    _flat_src_file_name = '__all__.md'

    targets = ('slate', 'slate-project', 'site')

    required_preprocessors_after = {
        'flatten': {
            'flat_src_file_name': _flat_src_file_name
        }
    },

    def copy_replace(self, src: str, dst: str):
        """
        Helper function to copy contents of src dir into dst dir replacing
        all files with same names
        """
        for src_dir, dirs, files in os.walk(src):
            dst_dir = src_dir.replace(src, dst, 1)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
            for file_ in files:
                src_file = os.path.join(src_dir, file_)
                dst_file = os.path.join(dst_dir, file_)
                if os.path.exists(dst_file):
                    os.remove(dst_file)
                copy(src_file, dst_dir)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._slate_config = self.config.get('backend_config',
                                             {}).get('slate', {})
        self._header = self._slate_config.get('header', {})

        self._slate_site_dir = \
            f'{self._slate_config.get("slug", self.get_slug())}.slate'
        self._slate_project_dir = \
            f'{self._slate_config.get("slug", self.get_slug())}.src'
        self._slate_repo_dir = self.project_path / '.slate/slaterepo'
        self._slate_tmp_dir = self.project_path / '.slate/_tmp'
        self._shards_dir = self.project_path /\
            self._slate_config.get('shards_path', 'shards')
        self._flat_src_file_path = self.working_dir / self._flat_src_file_name

        if self._slate_tmp_dir.exists():
            remove_tree(self._slate_tmp_dir)
        os.makedirs(self._slate_tmp_dir)

        self.logger = self.logger.getChild('slate')

        self.logger.debug(f'Backend inited: {self.__dict__}')

    def _add_header(self):
        """Add yaml-header into the main md file"""

        with open(self._flat_src_file_path, encoding='utf8') as md:
            content = md.read()
        header = yaml.dump(self._header,
                           default_flow_style=False,
                           allow_unicode=True)
        with open(self._flat_src_file_path, 'w', encoding='utf8') as md:
            md.write(f'---\n{header}\n---\n\n{content}')

    def _clone_repo(self):
        """Clone or update slate repository"""

        try:
            self.logger.debug(f'Cloning repository {SLATE_REPO}...')
            run(
                f'git clone {SLATE_REPO} {self._slate_repo_dir}',
                shell=True,
                check=True,
                stdout=PIPE,
                stderr=STDOUT
            )

        except CalledProcessError:
            self.logger.debug(f'Updating repository {SLATE_REPO}...')
            run('git pull',
                cwd=self._slate_repo_dir,
                shell=True,
                check=True,
                stdout=PIPE,
                stderr=STDOUT)

    def make(self, target: str) -> str:
        with spinner(f'Making {target}', self.logger, self.quiet):
            try:
                self._add_header()

                if self._slate_tmp_dir.exists():
                    remove_tree(self._slate_tmp_dir)
                os.makedirs(self._slate_tmp_dir)

                self._clone_repo()

                copy_tree(str(self._slate_repo_dir), str(self._slate_tmp_dir))
                if self._shards_dir.exists():
                    self.copy_replace(str(self._shards_dir),
                                      str(self._slate_tmp_dir))
                index_html = self._slate_tmp_dir / 'source/index.html.md'
                if index_html.exists():
                    os.remove(index_html)

                copyfile(self._flat_src_file_path, str(index_html) + '.erb')

                if target == 'site':
                    run(
                        f'bundle exec middleman build --clean',
                        cwd=self._slate_tmp_dir,
                        shell=True,
                        check=True,
                        stdout=PIPE,
                        stderr=STDOUT
                    )
                    if os.path.exists(self._slate_site_dir):
                        remove_tree(self._slate_site_dir)
                    copy_tree(str(self._slate_tmp_dir / 'build'),
                              str(self._slate_site_dir))
                    return f'{self._slate_site_dir}/'
                elif target == 'slate':
                    if os.path.exists(self._slate_project_dir):
                        remove_tree(self._slate_project_dir)
                    copy_tree(str(self._slate_tmp_dir),
                              str(self._slate_project_dir))
                    return f'{self._slate_project_dir}/'

            except Exception as exception:
                err = traceback.format_exc()
                self.logger.debug(err)
                raise type(exception)(f'Build failed: {err}')
