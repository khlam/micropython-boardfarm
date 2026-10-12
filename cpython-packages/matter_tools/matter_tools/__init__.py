"""Host-side Matter firmware building and board provisioning for ESP-Matter.

``matter_tools.build`` compiles and publishes firmware; ``matter_tools.provision``
mints, checks, and flashes one board's credentials. The callers that run them
inside Dockerfile.matter's stages live in ``tools/matter-build/``.
"""
