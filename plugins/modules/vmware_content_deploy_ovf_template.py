#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2020, Lev Goncharov <lev@goncharov.xyz>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: vmware_content_deploy_ovf_template
short_description: Deploy Virtual Machine from ovf template stored in content library.
description:
- Module to deploy virtual machine from ovf template in content library.
- All variables and VMware object names are case sensitive.
author:
- Lev Goncharv (@ultral)
notes:
- Tested on vSphere 6.7
requirements:
- python >= 2.6
- PyVmomi
- vSphere Automation SDK
options:
    ovf_template:
      description:
      - The name of OVF template from which VM to be deployed.
      type: str
      required: True
      aliases: ['ovf', 'template_src']
    content_library:
      description:
      - The name of the content library from where the template resides.
      type: str
      required: False
      version_added: '1.5.0'
    name:
      description:
      - The name of the VM to be deployed.
      type: str
      required: True
      aliases: ['vm_name']
    datacenter:
      description:
      - Name of the datacenter, where VM to be deployed.
      type: str
      required: True
    datastore:
      description:
      - Name of the datastore to store deployed VM and disk.
      type: str
      required: True
    folder:
      description:
      - Name of the folder in datacenter in which to place deployed VM.
      type: str
      required: True
    host:
      description:
      - Name of the ESX Host in datacenter in which to place deployed VM. The host has to be a member of the cluster that contains the resource pool.
      type: str
      required: True
    resource_pool:
      description:
      - Name of the resourcepool in datacenter in which to place deployed VM.
      type: str
      required: True
    cluster:
      description:
      - Name of the cluster in datacenter in which to place deployed VM.
      type: str
      required: False
    storage_provisioning:
      description:
      - Default storage provisioning type to use for all sections of type vmw:StorageSection in the OVF descriptor.
      type: str
      choices: [ thin, thick, eagerZeroedThick, eagerzeroedthick ]
extends_documentation_fragment: community.vmware.vmware_rest_client.documentation
'''

EXAMPLES = r'''
- name: Deploy Virtual Machine from OVF template in content library
  community.vmware.vmware_content_deploy_ovf_template:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    ovf_template: rhel_test_template
    datastore: Shared_NFS_Volume
    folder: vm
    datacenter: Sample_DC_1
    name: Sample_VM
    resource_pool: test_rp
  delegate_to: localhost

- name: Deploy Virtual Machine from OVF template in content library with eagerZeroedThick storage
  vmware_content_deploy_ovf_template:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    ovf_template: rhel_test_template
    datastore: Shared_NFS_Volume
    folder: vm
    datacenter: Sample_DC_1
    name: Sample_VM
    resource_pool: test_rp
    storage_provisioning: eagerZeroedThick
  delegate_to: localhost
'''

RETURN = r'''
vm_deploy_info:
  description: Virtual machine deployment message and vm_id
  returned: on success
  type: dict
  sample: {
        "msg": "Deployed Virtual Machine 'Sample_VM'.",
        "vm_id": "vm-1009"
    }
'''

import traceback

from ansible.module_utils.basic import AnsibleModule, env_fallback, missing_required_lib
from ansible.module_utils._text import to_native
from ansible_collections.community.vmware.plugins.module_utils.vmware_rest_client import VmwareRestClient
from ansible_collections.community.vmware.plugins.module_utils.vmware import PyVmomi

HAS_VAUTOMATION = False
VAUTOMATION_IMP_ERR = None
try:
    from com.vmware.vcenter.ovf_client import LibraryItem
    from com.vmware.vapi.std.errors_client import Error
    HAS_VAUTOMATION = True
except ImportError:
    VAUTOMATION_IMP_ERR = traceback.format_exc()


class VmwareContentDeployOvfTemplate(VmwareRestClient):
    def __init__(self, module):
        """Constructor."""
        super(VmwareContentDeployOvfTemplate, self).__init__(module)

        # Initialize member variables
        self.module = module
        self.pyv = PyVmomi(module=module)
        self.template_service = self.api_client.vcenter.vm_template.LibraryItems
        self.datacenter_id = None
        self.datastore_id = None
        self.library_item_id = None
        self.folder_id = None
        self.host_id = None
        self.cluster_id = None
        self.resourcepool_id = None

        # Get parameters
        self.template = self.params.get('template')
        self.library = self.params.get('library')
        self.vm_name = self.params.get('name')
        self.datacenter = self.params.get('datacenter')
        self.datastore = self.params.get('datastore')
        self.datastore_cluster = self.params.get('datastore_cluster')
        self.folder = self.params.get('folder')
        self.resourcepool = self.params.get('resource_pool')
        self.cluster = self.params.get('cluster')
        self.host = self.params.get('host')
        self.storage_provisioning = self.params.get('storage_provisioning')
        if self.storage_provisioning == 'eagerzeroedthick':
            self.storage_provisioning = 'eagerZeroedThick'

        if not HAS_VAUTOMATION:
            AnsibleModule.fail_json(self, msg=missing_required_lib('vSphere-Automation-SDK'),
                                    exception=VAUTOMATION_IMP_ERR)

        vm = self.pyv.get_vm()
        if vm:
            self.module.exit_json(
                changed=False,
                vm_deploy_info=dict(
                    msg="Virtual Machine '%s' already Exists." % self.vm_name,
                    vm_id=vm._moId,
                )
            )

    def deploy_vm_from_ovf_template(self):
        # Find the datacenter by the given datacenter name
        self.datacenter_id = self.get_datacenter_by_name(datacenter_name=self.datacenter)
        if not self.datacenter_id:
            self.module.fail_json(msg="Failed to find the datacenter %s" % self.datacenter)

        # Find the datastore by the given datastore name
        self.module.result['debug'] = {}
        if self.datastore:
            self.datastore_id = self.get_datastore_by_name(self.datacenter, self.datastore)
            self.module.result['debug']['ds_id'] = self.datastore_id
            if not self.datastore_id:
                self.module.fail_json(msg="Failed to find the datastore %s" % self.datastore)

        # Find the datastore by the given datastore cluster name
        if self.datastore_cluster and not self.datastore_id:
            dsc = self.pyv.find_datastore_cluster_by_name(self.datastore_cluster)
            if dsc:
                self.datastore_id = self.pyv.get_recommended_datastore(dsc)
                self.module.result['debug']['ds_id'] = self.datastore_id
            else:
                self.module.fail_json(msg="Failed to find the datastore cluster %s" % self.datastore_cluster)

        if not self.datastore_id:
            self.module.fail_json(msg="Failed to find the datastore using either datastore or datastore cluster")

        # Find the LibraryItem (Template) by the given LibraryItem name
        if self.library:
            self.library_item_id = self.get_library_item_from_content_library_name(
                self.template, self.library)
            if not self.library_item_id:
                self.module.fail_json(msg="Failed to find the library Item %s in content library %s" % (self.template, self.library))
        else:
            self.library_item_id = self.get_library_item_by_name(self.template)
            if not self.library_item_id:
                self.module.fail_json(msg="Failed to find the library Item %s" % self.template)

        # Find the folder by the given folder name
        self.folder_id = self.get_folder_by_name(self.datacenter, self.folder)
        if not self.folder_id:
            self.module.fail_json(msg="Failed to find the folder %s" % self.folder)

        # Verfy host exists if specified
        if self.host:
            self.host_id = self.get_host_by_name(self.datacenter, self.host)
            if not self.host_id:
                self.module.fail_json(msg="Failed to find the Host %s" % self.host)

        # Find the resourcepool by the given resourcepool name
        if self.resourcepool:
            self.resourcepool_id = self.get_resource_pool_by_name(self.datacenter, self.resourcepool, self.cluster, self.host)
            if not self.resourcepool_id:
                self.module.fail_json(msg="Failed to find the resource_pool %s" % self.resourcepool)
        elif self.cluster:
            self.cluster_id = self.get_cluster_by_name(self.datacenter, self.cluster)
            if not self.cluster_id:
                self.module.fail_json(msg="Failed to find the Cluster %s" % self.cluster)
            cluster_obj = self.api_client.vcenter.Cluster.get(self.cluster_id)
            self.resourcepool_id = cluster_obj.resource_pool

        if not self.resourcepool_id:
            self.module.fail_json(msg="Failed to find a resource pool either by name or cluster")

        deployment_target = LibraryItem.DeploymentTarget(
            resource_pool_id=self.resourcepool_id,
            folder_id=self.folder_id
        )

        self.ovf_summary = self.api_client.vcenter.ovf.LibraryItem.filter(
            ovf_library_item_id=self.library_item_id,
            target=deployment_target)

        self.deploy_spec = LibraryItem.ResourcePoolDeploymentSpec(
            name=self.vm_name,
            annotation=self.ovf_summary.annotation,
            accept_all_eula=True,
            network_mappings=None,
            storage_mappings=None,
            storage_provisioning=self.storage_provisioning,
            storage_profile_id=None,
            locale=None,
            flags=None,
            additional_parameters=None,
            default_datastore_id=self.datastore_id)

        result = {
            'succeeded': False
        }
        try:
            result = self.api_client.vcenter.ovf.LibraryItem.deploy(self.library_item_id, deployment_target, self.deploy_spec)
        except Error as error:
            self.module.fail_json(msg="%s" % self.get_error_message(error))
        except Exception as err:
            self.module.fail_json(msg="%s" % to_native(err))

        if result.succeeded:
            self.module.exit_json(
                changed=True,
                vm_deploy_info=dict(
                    msg="Deployed Virtual Machine '%s'." % self.vm_name,
                    vm_id=result.resource_id.id,
                )
            )
        self.module.exit_json(changed=False,
                              vm_deploy_info=dict(msg="Virtual Machine deployment failed", vm_id=''))


def main():
    argument_spec = VmwareRestClient.vmware_client_argument_spec()
    argument_spec.update(
        template=dict(
            type='str',
            aliases=[
                'ovf',
                'ovf_template',
                'template_src'
            ],
            required=True
        ),
        library=dict(
            type='str',
            aliases=[
                'content_library'
            ],
            required=False
        ),
        name=dict(
            type='str',
            aliases=[
                'vm_name'
            ],
            required=True
        ),
        datacenter=dict(
            type='str',
            required=True
        ),
        datastore=dict(
            type='str',
            required=False
        ),
        datastore_cluster=dict(
            type='str',
            required=False
        ),
        folder=dict(
            type='str',
            default='vm'
        ),
        host=dict(
            type='str',
            required=False
        ),
        resource_pool=dict(
            type='str',
            required=False
        ),
        cluster=dict(
            type='str',
            required=False
        ),
        storage_provisioning=dict(
            type='str',
            choices=[
                'thin',
                'thick',
                'eagerZeroedThick',
                'eagerzeroedthick'
            ],
            default='thin',
            fallback=(
                env_fallback,
                ['VMWARE_STORAGE_PROVISIONING']
            )
        ),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[
            ['datastore', 'datastore_cluster'],
        ],
    )
    result = {'failed': False, 'changed': False}
    vmware_contentlib_create = VmwareContentDeployOvfTemplate(module)
    if module.check_mode:
        result.update(
            vm_name=module.params['name'],
            changed=True,
            desired_operation='Create VM with PowerOff State',
        )
        module.exit_json(**result)
    vmware_contentlib_create.deploy_vm_from_ovf_template()


if __name__ == '__main__':
    main()
