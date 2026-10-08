`cloud-config-26.1.json` is an unmodified (formatting only) copy of the official
cloud-init 26.1 schema:
https://github.com/canonical/cloud-init/blob/26.1/cloudinit/config/schemas/schema-cloud-config-v1.json

Copyright Canonical Ltd. Distributed under GPLv3 or Apache-2.0, as described in
LICENSE.cloud-init. Validation is offline; supported fields correspond to 26.1.
The application additionally rejects duplicate keys, aliases, excessive nesting,
module-list overrides and conflicting SSH password authentication settings.
