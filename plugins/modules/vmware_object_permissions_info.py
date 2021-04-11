#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright: (c) 2021, Paul Knight <paul.knight@delaware.gov>
# SPDX-License-Identifier: GPL-3.0-or-later
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: vmware_object_permission_info
short_description: Gather permissions on an object
description: This module can be used to obtain object permissions on the given host.
author:
- Paul Knight (@n3pjk)
notes:
  - Tested on ESXi 6.5, vSphere 6.7
  - The ESXi login user must have the appropriate rights to administer permissions.
  - Permissions for a distributed switch must be defined and managed on either the datacenter or a folder containing the switch.
requirements:
  - "python >= 2.7"
  - PyVmomi
options:
  principal:
    description:
    - The name of the user.
    - Required if C(group) is not specified.
    - If specifying domain user, required separator of domain uses backslash.
    type: str
  group:
    description:
    - The name of the group.
    - Required if C(principal) is not specified.
    type: str
  moid:
    description:
    - The managed object id of the object.
  object_name:
    description:
    - The name of the object name.
    type: str
    required: True
  object_type:
    description:
    - The object type being targeted.
    - Required if C(object_name) is specified.
    choices: ['Folder', 'VirtualMachine', 'Datacenter', 'ResourcePool',
              'Datastore', 'Network', 'HostSystem', 'ComputeResource',
              'ClusterComputeResource', 'DistributedVirtualSwitch']
    type: str
extends_documentation_fragment:
- community.vmware.vmware.documentation

'''

EXAMPLES = r'''
- name: Assign user to VM folder
  community.vmware.vmware_object_role_permission:
    hostname: '{{ esxi_hostname }}'
    username: '{{ esxi_username }}'
    password: '{{ esxi_password }}'
    role: Admin
    principal: user_bob
    object_name: services
    state: present
  delegate_to: localhost

- name: Remove user from VM folder
  community.vmware.vmware_object_role_permission:
    hostname: '{{ esxi_hostname }}'
    username: '{{ esxi_username }}'
    password: '{{ esxi_password }}'
    role: Admin
    principal: user_bob
    object_name: services
    state: absent
  delegate_to: localhost

- name: Assign finance group to VM folder
  community.vmware.vmware_object_role_permission:
    hostname: '{{ esxi_hostname }}'
    username: '{{ esxi_username }}'
    password: '{{ esxi_password }}'
    role: Limited Users
    group: finance
    object_name: Accounts
    state: present
  delegate_to: localhost

- name: Assign view_user Read Only permission at root folder
  community.vmware.vmware_object_role_permission:
    hostname: '{{ esxi_hostname }}'
    username: '{{ esxi_username }}'
    password: '{{ esxi_password }}'
    role: ReadOnly
    principal: view_user
    object_name: rootFolder
    state: present
  delegate_to: localhost

- name: Assign domain user to VM folder
  community.vmware.vmware_object_role_permission:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    validate_certs: false
    role: Admin
    principal: "vsphere.local\\domainuser"
    object_name: services
    state: present
  delegate_to: localhost
'''

RETURN = r'''
changed:
    description: whether or not a change was made to the object's role
    returned: always
    type: bool
'''

try:
  from pyVmomi import vim, vmodl
except ImportError:
  pass

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native
from ansible_collections.community.vmware.plugins.module_utils.vmware import PyVmomi, vmware_argument_spec, find_obj


class VMwareObjectPermissionsInfo(PyVmomi):
  def __init__(self, module):
    super(VMwareObjectPermissionsInfo, self).__init__(module)
    self.module = module
    self.params = module.params
    self.result = {}
    self.is_group = False
    self.auth_manager = self.content.authorizationManager

    if self.params.get('principal', None) is not None:
      self.applied_to = self.params['principal']
    elif self.params.get('group', None) is not None:
      self.applied_to = self.params['group']
      self.is_group = True

    self.get_object()
    self.get_perms()
    self.result['permissions'] = self.to_json(self.current_perms)
    self.module.exit_json(**self.result)

  def get_perms(self):
    self.current_perms = self.auth_manager.RetrieveEntityPermissions(self.current_obj, False)

  def get_object(self):
    # find_obj doesn't include rootFolder
    if self.params['object_type'] == 'Folder' and self.params['object_name'] == 'rootFolder':
      self.current_obj = self.content.rootFolder
      return
    try:
      getattr(vim, self.params['object_type'])
    except AttributeError:
      self.module.fail_json(msg="Object type %s is not valid." % self.params['object_type'])
    self.current_obj = find_obj(content=self.content,
                                vimtype=[getattr(vim, self.params['object_type'])],
                                name=self.params['object_name'])

    if self.current_obj is None:
      self.module.fail_json(
          msg="Specified object %s of type %s was not found."
          % (self.params['object_name'], self.params['object_type'])
      )
    if self.params['object_type'] == 'DistributedVirtualSwitch':
      msg = "You are applying permissions to a Distributed vSwitch. " \
            "This will probably fail, since Distributed vSwitches inherits permissions " \
            "from the datacenter or a folder level. " \
            "Define permissions on the datacenter or the folder containing the switch."
      self.module.warn(msg)


def main():
  argument_spec = vmware_argument_spec()
  argument_spec.update(
      dict(
          moid=dict(
              type='str'
              ),
          object_name=dict(
              type='str'
              ),
          object_type=dict(
              type='str',
              default='Folder',
              choices=[
                  'Folder',
                  'VirtualMachine',
                  'Datacenter',
                  'ResourcePool',
                  'Datastore',
                  'Network',
                  'HostSystem',
                  'ComputeResource',
                  'ClusterComputeResource',
                  'DistributedVirtualSwitch',
                  ],
              ),
          principal=dict(
              type='str'
              ),
          group=dict(
              type='str'
              ),
          )
  )

  module = AnsibleModule(
      argument_spec=argument_spec,
      supports_check_mode=True,
      mutually_exclusive=[
          ['moid', 'object_name'],
          ['principal', 'group']
          ],
      required_one_of=[
          ['moid', 'object_name'],
          ['principal', 'group']
          ],
      required_together=[
          ['object_name', 'object_type']
          ]
  )

  vmware_object_permission = VMwareObjectPermissionsInfo(module)
  vmware_object_permission.process_state()


if __name__ == '__main__':
    main()
