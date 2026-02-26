SHELL := /bin/bash

.PHONY: help bootstrap init up up-full down restart status logs health governance smoke case-smoke incident-check security-check release-readiness metrics load frontend-check preflight test

help:
	./onco help

bootstrap:
	./onco bootstrap

init:
	./onco init

up:
	./onco up

up-full:
	./onco up --full

down:
	./onco down

restart:
	./onco restart

status:
	./onco status

logs:
	./onco logs

health:
	./onco health

governance:
	./onco governance

smoke:
	./onco smoke

case-smoke:
	./onco case-smoke

incident-check:
	./onco incident-check

security-check:
	./onco security-check

release-readiness:
	./onco release-readiness

metrics:
	./onco metrics

load:
	./onco load

frontend-check:
	./onco frontend-check

preflight:
	./onco preflight

test:
	./onco test
