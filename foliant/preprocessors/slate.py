import re
from shutil import copy
from pathlib import Path, PosixPath
from os.path import relpath
from uuid import uuid1

from foliant.preprocessors.base import BasePreprocessor


class Preprocessor(BasePreprocessor):
    # defaults = {'project_dir_name': 'slate'}

    _image_pattern = re.compile(r'\!\[(?P<caption>.*)\]\((?P<path>((?!:\/\/).)+)\)')

    def _collect_images(self, content: str, md_file_path: PosixPath) -> str:
        '''Find images outside the working directory, copy them into the
        working directory, and replace the paths in the md-files.

        This is necessary because Slate can't deal with images outside the
        project dir.

        :param content: Markdown content
        :param md_file_path: Path to the Markdown file with content ``content``

        :returns: Markdown content with image paths pointing within the source
                  directory
        '''

        self.logger.debug(f'Looking for images in {md_file_path}.')

        def _sub(image):
            image_caption = image.group('caption')
            # make absolute and resolve symlinks
            image_path = (md_file_path.parent / Path(image.group('path'))).resolve()

            self.logger.debug(f'Detected image: caption="{image_caption}", path={image_path}')

            if self.working_dir.resolve() not in image_path.parents:
                self.logger.debug('Image outside source directory.')

                self._collected_imgs_path.mkdir(exist_ok=True)

                # future image name after copying
                collected_img_path = (
                    self._collected_imgs_path / f'{image_path.stem}_{str(uuid1())}'
                ).with_suffix(image_path.suffix)

                copy(image_path, collected_img_path)

                self.logger.debug(f'Image copied to {collected_img_path}')

                rel_img_path = Path(relpath(collected_img_path, md_file_path.parent)).as_posix()

            else:
                self.logger.debug('Image inside source directory.')
                rel_img_path = Path(relpath(image_path, md_file_path.parent)).as_posix()

            img_ref = f'![{image_caption}]({rel_img_path})'

            self.logger.debug(f'Replacing with: {img_ref}')

            return img_ref

        return self._image_pattern.sub(_sub, content)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # temporary dir for keeping collected images
        self._collected_imgs_path = self.working_dir / f'img_{str(uuid1())}'

        self.logger = self.logger.getChild('slate')

        self.logger.debug(f'Preprocessor inited: {self.__dict__}')

    def apply(self):
        for markdown_file_path in self.working_dir.rglob('*.md'):
            with open(markdown_file_path, encoding='utf8') as markdown_file:
                content = markdown_file.read()
            processed_content = self._collect_images(content, markdown_file_path)
            with open(markdown_file_path, 'w', encoding='utf8') as markdown_file:
                markdown_file.write(processed_content)

        self.logger.debug('Preprocessor applied.')
