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

# Run the member-loop-only integration check.
# After completion, inspect the decisive output:
#   llmoses/outputs/runs/<RUN_ID>/state/run-1/step-1.json
# Member B's bscore must read [0.0, 1.0, 0.0, 1.0].
test-member: $(OUTPUTS_HOST)/logs $(OUTPUTS_HOST)/states
	docker run --rm \
		-v "$(OUTPUTS_HOST):$(OUTPUTS_CNT)" \
		$(IMAGE) \
		bash -c 'cd $(WORKDIR) && run.sh llmoses/llmoses-tests/member-only-test.metta -s; \
		         echo "--- latest run dir ---"; \
		         latest=$$(ls -1dt $(OUTPUTS_CNT)/runs/*/ 2>/dev/null | head -1); \
		         echo "$$latest"; \
		         echo "--- member B bscore (expect [0.0,1.0,0.0,1.0]) ---"; \
		         cat "$$latest/state/run-1/step-1.json" 2>/dev/null \
		           | python3 -c "import sys,json; d=json.load(sys.stdin); \
		             [print(m[\"program_id\"],m[\"bscore\"]) for m in d[\"metapopulation\"][\"members\"]]" \
		           || echo "(step-1.json not found — run may have failed)"'

# Probe how OS.length reduces (and whether arithmetic/if-guard reduce at all)
# in exactly the same scope as the member loop. Read P1-P7 in the printed output.
probe-os-length: $(OUTPUTS_HOST)/logs $(OUTPUTS_HOST)/states
	docker run --rm \
		-v "$(OUTPUTS_HOST):$(OUTPUTS_CNT)" \
		$(IMAGE) \
		bash -c 'cd $(WORKDIR) && run.sh llmoses/llmoses-tests/os-length-probe.metta -s'
