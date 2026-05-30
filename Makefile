# ============================================================================
# metta-LLmoses – Docker convenience targets
# ============================================================================
# Usage:
#   make build   – build (or rebuild) the image
#   make shell   – open an interactive bash shell inside the container
#   make run     – run the default CMD (full metta-moses test suite)
#   make clean   – remove the local image
#
# The host directory ./llmoses/outputs/ is bind-mounted into the container
# so that wrapper output and logs persist on the host even after the
# container exits.
# ============================================================================

IMAGE        := metta-llmoses
WORKDIR      := /workspace/metta-moses

OUTPUTS_HOST := $(abspath llmoses/outputs)
OUTPUTS_CNT  := $(WORKDIR)/llmoses/outputs

# Create host-side directories if they don't exist yet.
$(OUTPUTS_HOST)/logs:
	mkdir -p $@

$(OUTPUTS_HOST)/states:
	mkdir -p $@

.PHONY: build clean shell run

build:
	docker build --tag $(IMAGE) .

clean:
	docker image rm --force $(IMAGE)

shell: $(OUTPUTS_HOST)/logs $(OUTPUTS_HOST)/states
	docker run --rm -it \
		-v "$(OUTPUTS_HOST):$(OUTPUTS_CNT)" \
		$(IMAGE) bash

run: $(OUTPUTS_HOST)/logs $(OUTPUTS_HOST)/states
	docker run --rm \
		-v "$(OUTPUTS_HOST):$(OUTPUTS_CNT)" \
		$(IMAGE)
