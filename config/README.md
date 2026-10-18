# config/

Settings for ai-leverage itself on this machine: what its own scripts read,
as opposed to the `.env` files next to each engine and service, which Compose
hands to their containers.

Each setting has a `.template` here, committed, with every option explained.
Your own copy has the same name without `.template` and is ignored by git, so
your choices stay on your machine. The menus write it for you, and you can
edit it by hand just as well.

| File | What it's for |
|------|---------------|
| `model-fit.conf` | What the model fit (**Models › Tuning › Fit** in the menu) plans for: the context you need, whether the PC's memory may help, how many conversations run at once |
| `menu.conf` | How `manage.sh`'s menu looks: its colour theme, which the menu remembers when you pick one (**ctrl+p**, then **Theme**) |
