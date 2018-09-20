# Slate Backend for Foliant

Slate backend generates API documentation from Markdown using [Slate docs generator](https://github.com/lord/slate).

This backend operates two targets:

* `site` — build a standalone website;
* `slate` — generate a slate project out from your Foliant project.

## Installation

```bash
$ pip install foliantcontrib.slate
```

## Usage

Convert Foliant project to Slate:

```bash
$ foliant make slate
✔ Parsing config
✔ Applying preprocessor flatten
✔ Making slate
─────────────────────
Result: My_Project-2018-09-19.src/
```

Build a standalone website:

```bash
$ foliant make site
✔ Parsing config
✔ Applying preprocessor flatten
✔ Making site
─────────────────────
Result: My_Project-2018-09-19.slate/
```

## Config

You don't have to put anything in the config to use Slate backend. If it is installed, Foliant detects it.

To customize the output, use options in `backend_config.slate` section:

```yaml
backend_config:
  slate:
    shards_path: data/shards
    header:
        title: My API documentation
        language_tabs:
          - xml: Response example
        search: true
```

`shards_path`
:   Path to the shards directory relative to Foliant project dir. Shards allow you to customize Slate's layout, add scripts etc. More info on shards in the following section. Default: `shards`

`header`
:   Params to be copied into the beginning of Slate main Markdown file `index.html.md`. They allow you to change the title of the website, toggle search and add language tabs. More info in [Slate Wiki](https://github.com/lord/slate/wiki).

## About shards

Shards is just a folder with files which will be copied into the generated Slate project replacing all files in there. If you follow the Slate project structure you can replace stylesheets, scripts, images, layouts etc to customize the view of the resulting site.

For example, I want to customize standard Slate stylesheets. I look at the Slate repo and see that they lie in the folder `<slate>/source/stylesheets`. I create new stylesheets with the same names as the original ones and put them into my shards dir like that:

```
shards\
    source\
        stylesheets\
            _variables.scss
            screen.css.scss
```

These stylesheets will replace the original ones in the Slate project just before the website will be baked. So the page will use my styles in the end.