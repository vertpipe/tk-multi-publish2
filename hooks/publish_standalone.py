# Copyright Netherlands Film Academy 2020

import os
import pprint
import traceback

import sgtk
from sgtk.util.filesystem import copy_file, ensure_folder_exists

HookBaseClass = sgtk.get_hook_baseclass()


class StandalonePublishPlugin(HookBaseClass):

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts
        as part of its environment configuration.
        """

        settings = super(StandalonePublishPlugin, self).settings

        # valid values for the Publish Template setting should be in the following format:
        # [
        #    {"ext": ["ma", "mb"],
        #     "entity_type": "Asset",
        #     "template": "maya_asset_publish"},
        #    {"ext": ["ma", "mb"],
        #     "entity_type": "Shot",
        #     "template": "maya_shot_publish"}
        # ]
        settings["Publish Template"] = {
            "type": "list",
            "default":[]
        }
        return settings

    def _copy_work_to_publish(self, settings, item):
        """
        Copies the source file to the publish location.
        Handling of sequence paths is not implemented, see
        the base hook for an example on how to go about doing that.
        """

        #TODO: rework this to handle sequences.
        source_path = item.properties.path
        publish_path = self.get_publish_path(settings, item)

        if source_path == publish_path:
            # no need to copy since the publish path is the same as the source.
            self.logger.debug(
                "Source path: %s is the same as the publish path, no copying needed."
                % (source_path)
            )
            return

        # copy the file
        try:
            publish_folder = os.path.dirname(publish_path)
            ensure_folder_exists(publish_folder)
            copy_file(source_path, publish_path)
        except Exception:
            raise Exception(
                "Failed to copy source file from '%s' to '%s'.\n%s"
                % (source_path, publish_path, traceback.format_exc())
            )

        self.logger.debug(
            "Copied source file '%s' to publish file '%s'."
            % (source_path, publish_path)
        )

    def get_publish_template(self, settings, item):
        """
        Get a publish template for the supplied settings and item.

        :param settings: This plugin instance's configured settings
        :param item: The item to determine the publish template for

        :return: A template representing the publish path of the item or
            None if no template could be identified.
        """
        publish_templates = settings.get("Publish Template", [])

        # Since each publish template setting has an assigned entity type
        # We need to try and get the item context's entity type to find an appropriate template.
        entity_type = item.context.entity.get("type") if item.context.entity else None

        # Now get the publish file extension.
        path = item.properties.path
        # get the publish path components
        path_info = self.parent.util.get_file_path_components(path)
        # determine the publish type
        extension = path_info["extension"]

        for template_config in publish_templates.value:
            if extension in template_config["ext"] and entity_type == template_config["entity_type"]:
                return self.sgtk.templates[template_config["template"]]


    def get_publish_path(self, settings, item):
        """
        Get a publish path for the supplied settings and item.

        :param settings: This plugin instance's configured settings
        :param item: The item to determine the publish path for

        :return: A string representing the output path to supply when
            registering a publish for the supplied item

        Extracts the publish path via the configured work and publish templates
        if possible.
        """

        # publish type explicitly set or defined on the item
        publish_path = item.get_property("publish_path")
        if publish_path:
            return publish_path

        # fall back to template/path logic
        # We need to be able to resolve the Publish Template keys.
        # This can be done by two methods

        # 1. If a work template is provided and the file to publish path
        #    matches that template, we can extract the keys from that
        #    path and use them to resolve the publish path.
        #    This assumes that the work file and publish file share the same keys

        # 2. If a work template is not provided or can't be inferred from the path
        #    We need to use the context to try and resolve as many of the
        #    template keys as possible, and the provide the ones that can't
        #    be derived from context alone, such as the name or the version.


        path = item.properties.path

        work_template = item.properties.get("work_template")
        publish_template = self.get_publish_template(settings, item)

        self.logger.debug("publish_template: %s" % publish_template)
        self.logger.debug("work_template: %s" % work_template)

        fields = []
        publish_path = None

        # See if we have a Publish template and optionally a
        # work template and gather the field data so we can use Toolkit
        # to resolve a path using the template.
        if work_template and publish_template:
            # We have a work template so we can try and get
            # the fields from the path using that.
            if work_template.validate(path):
                fields = work_template.get_fields(path)
        elif publish_template:
            # There is no work template provided, check to see if
            # we can match a template from the path.
            work_template = self.sgtk.template_from_path(path)
            if work_template:
                fields = work_template.get_fields(path)
            else:
                # No template could be found from the path, so it is likely this
                # source file lives out side of the Toolkit structure currently.
                # We need to try and resolve the template path using the context.
                fields = item.context.as_template_fields(publish_template)

                # Perform a check for common keys that can't be resolved from the context
                # and try to provide values.
                # If your template contains additional fields that can't be resolved from context
                # you must supply them here.
                if "name" in publish_template.keys:
                    # This method by default returns the name plus the extension, so we need to strip it off.
                    file_name = self.get_publish_name(settings, item)
                    name, ext = os.path.splitext(file_name)
                    fields["name"] = name
                if "version" in publish_template.keys:
                    fields["version"] = self.get_publish_version(settings, item)
                if "extension" in publish_template.keys:
                    path_info = self.parent.util.get_file_path_components(path)
                    fields["extension"] = path_info["extension"]

        self.logger.debug("publish_template: %s" % publish_template)
        self.logger.debug("work_template: %s" % work_template)

        # Now if we have a publish template we can use the fields
        # to try and resolve the path.
        if publish_template:
            missing_keys = publish_template.missing_keys(fields)

            if missing_keys:
                self.logger.warning(
                    "Not enough keys to apply work fields (%s) to "
                    "publish template (%s)" % (fields, publish_template)
                )
            else:
                publish_path = publish_template.apply_fields(fields)
                self.logger.debug(
                    "Used publish template to determine the publish path: %s"
                    % (publish_path,)
                )


        if not publish_path:
            publish_path = path
            self.logger.debug(
                "Could not validate a publish template. Publishing in place."
            )

        return publish_path
