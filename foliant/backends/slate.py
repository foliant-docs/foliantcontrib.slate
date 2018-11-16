import os
import yaml
import traceback

from shutil import copy, move
from subprocess import run, PIPE, STDOUT, CalledProcessError

from foliant.utils import spinner
from foliant.backends.base import BaseBackend
from distutils.dir_util import copy_tree, remove_tree
from pathlib import PosixPath

SLATE_REPO = 'https://github.com/lord/slate.git'


def copy_replace(src: str, dst: str):
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


class Chapters():
    """
    Helper class converting chapter list of complicated structure
    into a plain list of chapter names or path to actual md files
    in the working_dir.
    """

    def __init__(self,
                 chapters: list,
                 working_dir: PosixPath):
        self.set_chapters(chapters)
        self._working_dir = working_dir

    def __len__(self):
        return len(self._chapters)

    def set_chapters(self, chapters: list):
        def flatten_seq(seq):
            """convert a sequence of embedded sequences into a plain list"""
            result = []
            vals = seq.values() if type(seq) == dict else seq
            for i in vals:
                if type(i) in (dict, list):
                    result.extend(flatten_seq(i))
                else:
                    result.append(i)
            return result
        self._chapters = flatten_seq(chapters)

    @property
    def chapters(self):
        return self._chapters

    @property
    def paths_g(self):
        return (self._working_dir / chap for chap in self._chapters)


class Backend(BaseBackend):

    targets = ('slate', 'site')

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
        self._chapters = Chapters(self.config['chapters'], self.working_dir)

        self.required_preprocessors_after = {
            'slate': {}
        }

        if self._slate_tmp_dir.exists():
            remove_tree(self._slate_tmp_dir)
        os.makedirs(self._slate_tmp_dir)

        self.logger = self.logger.getChild('slate')

        self.logger.debug(f'Backend inited: {self.__dict__}')

    def _add_shards(self):
        """move shards into slate tmp dir"""

        shards = self._slate_config.get('shards', 'shards')
        if type(shards) == str:
            shards = [shards]
        for shard in shards:
            shard_path = self.project_path / shard
            if shard_path.exists():
                copy_replace(str(shard_path),
                             str(self._slate_tmp_dir))

    def _add_header(self, chapter_path: PosixPath or str):
        """
        Add yaml-header into the main md file

        chapter_path - path to md file where the header should be inserted
        """

        with open(chapter_path, encoding='utf8') as md:
            content = md.read()
        # copy header dict into variable
        header_dict = dict(self._header)

        # prepend includes by all chapters except the first one
        if len(self._chapters) > 1:
            header_dict['includes'] = self._chapters.chapters[1:] +\
                header_dict.get('includes', [])

        if header_dict:
            header = yaml.dump(header_dict,
                               default_flow_style=False,
                               allow_unicode=True)
            with open(chapter_path, 'w', encoding='utf8') as md:
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
        with spinner(f'Making {target}', self.logger, self.quiet, self.debug):
            try:
                chapters = self._chapters.paths_g
                src_path = self._slate_tmp_dir / 'source/'

                # delete old slate project
                if self._slate_tmp_dir.exists():
                    remove_tree(self._slate_tmp_dir)
                os.makedirs(self._slate_tmp_dir)

                # get base slate project
                self._clone_repo()

                # assemble project from base repo and shards
                copy_tree(str(self._slate_repo_dir), str(self._slate_tmp_dir))
                self._add_shards()

                # remove base source files
                index_html = src_path / 'index.html.md'
                if index_html.exists():
                    os.remove(index_html)
                errors_md = src_path / 'includes/_errors.md'
                if errors_md.exists():
                    os.remove(errors_md)

                # replace index.html.md with the first chapter
                chapter_path = next(chapters)
                self._add_header(chapter_path)
                # without erb extension ruby includes won't work
                move(chapter_path, str(index_html) + '.erb')
                # copyfile(chapter_path, str(index_html) + '.erb')

                # copy all chapters except the first one into includes folder
                for chapter_path in chapters:
                    move(chapter_path, str(src_path / 'includes'))

                # move all directories (supposedly with images) into source
                for item in self.working_dir.glob('*'):
                    if item.is_dir():
                        move(str(item), str(src_path / 'images'))

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
