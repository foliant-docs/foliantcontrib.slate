import os
import yaml
import shutil
import traceback
import re

from shutil import copy
from subprocess import run, PIPE, STDOUT, CalledProcessError

from foliant.utils import spinner, output
from foliant.backends.base import BaseBackend
from distutils.dir_util import copy_tree, remove_tree
from pathlib import PosixPath, Path
from foliant.meta_commands.generate.patterns import YFM_PATTERN

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


def unique_name(dest_dir: str or PosixPath, old_name: str) -> str:
    """
    Check if file with old_name exists in dest_dir. If it does —
    add incremental numbers until it doesn't.
    """
    counter = 1
    dest_path = Path(dest_dir)
    name = old_name
    while (dest_path / name).exists():
        counter += 1
        name = f'_{counter}'.join(os.path.splitext(old_name))
    return name


class Chapters:
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

    _flat_src_file_name = '__all__.md'

    targets = ('slate', 'site')

    required_preprocessors_after = {
        'flatten': {
            'flat_src_file_name': _flat_src_file_name
        }
    }

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
        Add yaml-header from config into the main md file.

        chapter_path - path to md file where the header should be inserted
        """
        with open(chapter_path, encoding='utf8') as md:
            content = md.read()
        # copy header dict into variable
        header_dict = dict(self._header)

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

    def _process_images(self, source: str, target_dir: str or PosixPath) -> str:
        """
        Cleanup target_dir. Copy local images to `target_dir` with unique names
        and update their definitions with the new filenames.

        `source` — string with HTML source code to search images in;
        `rel_dir` — path relative to which image paths are determined.

        Returns a tuple: (new_source, attachments)

        new_source — a modified source with correct image paths
        """

        def _sub(image):
            image_caption = image.group('caption')
            image_path = image.group('path')

            # leave external images as is
            if image_path.startswith('http'):
                return image.group(0)

            image_path = Path(image_path)

            self.logger.debug(f'Found image: {image.group(0)}')

            new_name = unique_name(target_dir, image_path.name)
            new_path = Path(target_dir) / new_name

            self.logger.debug(f'Copying image into: {new_path}')
            shutil.copy(image_path, new_path)

            img_ref = f'![{image_caption}](images/{new_name})'

            self.logger.debug(f'Converted image ref: {img_ref}')
            return img_ref

        image_pattern = re.compile(r'!\[(?P<caption>.*?)\]\((?P<path>.+?)\)')
        self.logger.debug('Processing images')

        return image_pattern.sub(_sub, source)

    def make(self, target: str) -> str:
        with spinner(f'Making {target}', self.logger, self.quiet, self.debug):
            try:
                src_path = self._slate_tmp_dir / 'source/'
                img_path = src_path / 'images'
                source_path = self.working_dir / self._flat_src_file_name

                # delete old slate project
                shutil.rmtree(self._slate_tmp_dir, ignore_errors=True)
                self._slate_tmp_dir.mkdir(parents=True)

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

                # process images and save source in slate folder
                with open(source_path) as f:
                    source = f.read()
                processed_source = self._process_images(source, img_path)

                with open(str(index_html) + '.erb', 'w') as f:
                    f.write(processed_source)

                self._add_header(str(index_html) + '.erb')

                if target == 'site':
                    try:
                        r = run(
                            f'bundle exec middleman build --clean',
                            cwd=self._slate_tmp_dir,
                            shell=True,
                            check=True,
                            stdout=PIPE,
                            stderr=STDOUT
                        )
                    except CalledProcessError as e:
                        raise RuntimeError(e.output.decode('utf8', errors='ignore'))
                    command_output_decoded = r.stdout.decode('utf8', errors='ignore')
                    output(command_output_decoded, self.quiet)
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
