from wagtail import hooks

from .viewsets import page_tree_viewset


@hooks.register("register_admin_viewset")
def register_pagetree_viewset():
    return page_tree_viewset
