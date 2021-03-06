#!/usr/bin/env python2
#
# Copyright (C) Microsoft Corporation, All rights reserved.

"""Sandbox module."""

import os
import sys
import time
import traceback
from Queue import Queue, Empty

import configuration
import tracer
from automationconstants import jobstatus
from automationconstants import pendingactions
from httpclientfactory import HttpClientFactory
from job import Job
from jrdsclient import JRDSClient
from workerexception import *

routine_loop = True
job_map = {}


def safe_loop(func):
    def decorated_func(*args, **kwargs):
        global routine_loop
        while routine_loop:
            try:
                func(*args, **kwargs)
            except Exception:
                tracer.log_exception_trace(traceback.format_exc())
                time.sleep(1)  # allow the trace to make it to stdout (since traces are background threads)

                # this will work as long as all threads are daemon
                # daemon threads are only supported in 2.6+
                sys.exit(1)
            time.sleep(configuration.get_jrds_get_job_actions_polling_freq())

    return decorated_func


class Sandbox:
    def __init__(self):
        self.sandbox_id = os.environ["sandbox_id"]
        tracer.log_sandbox_starting(os.getpid())

        http_client_factory = HttpClientFactory(configuration.get_jrds_cert_path(), configuration.get_jrds_key_path(),
                                                configuration.get_verify_certificates())
        http_client = http_client_factory.create_http_client(sys.version_info)
        self.jrds_client = JRDSClient(http_client)

    @staticmethod
    def stop_tracking_terminated_jobs():
        terminated_job_ids = []

        # clean up finished jobs
        for job_id, job_tuple in job_map.items():
            if job_tuple[0].isAlive() is False:
                try:
                    job_tuple[2].get(block=False)
                    raise SandboxRuntimeException()
                except Empty:
                    pass
                terminated_job_ids.append(job_id)

        for job_id in terminated_job_ids:
            removal = job_map.pop(job_id, None)
            if removal is not None:
                tracer.log_sandbox_stopped_tracking_job(job_id)

    @safe_loop
    def routine(self):
        # clean up finished jobs
        self.stop_tracking_terminated_jobs()

        # get job actions
        try:
            job_actions = self.jrds_client.get_job_actions(self.sandbox_id)
        except JrdsSandboxTerminated:
            tracer.log_sandbox_jrds_closure_request()
            global routine_loop
            routine_loop = False
            return

        for job_action in job_actions:
            job_id = job_action["JobId"]
            job_data = self.jrds_client.get_job_data(job_id)
            job_pending_action = job_data.pending_action
            job_status = job_data.job_status

            # issue pending action
            if job_pending_action == pendingactions.ACTIVATE_ENUM_INDEX or \
                    (job_pending_action is None and job_status == jobstatus.ACTIVATING_ENUM_INDEX) or \
                    (job_pending_action is None and job_status == jobstatus.RUNNING_ENUM_INDEX):
                tracer.log_sandbox_pending_action_activate_detected(job_id, job_status, job_pending_action)
                # check if the specified job is already running to prevent duplicate
                if job_id in job_map:
                    continue

                # create and start the new job
                job_message_queue = Queue()
                job_thread_exception_queue = Queue()
                job = Job(self.sandbox_id, job_id, job_message_queue, self.jrds_client, job_thread_exception_queue)
                job_map[job_id] = (job, job_message_queue, job_thread_exception_queue)
                tracer.log_sandbox_started_tracking_job(job_id)
                job.start()
            elif job_pending_action == pendingactions.STOP_ENUM_INDEX:
                tracer.log_sandbox_pending_action_stop_detected(job_id, job_status, job_pending_action)
                # check if the specified job is already running before issuing pending action
                if job_id not in job_map:
                    continue

                # propagate pending action to job thread
                job_map[job_id][1].put(job_pending_action)
            elif job_pending_action is None:
                tracer.log_sandbox_no_pending_action_detected(job_id, job_status)
            else:
                tracer.log_sandbox_unsupported_pending_action_detected(job_id, job_status, job_pending_action)


def main():
    # configuration has to be read first thing
    configuration.set_config({configuration.COMPONENT: "sandbox"})
    configuration.set_config({configuration.WORKING_DIRECTORY_PATH: os.getcwd()})
    # do not trace anything before this point

    sandbox = Sandbox()
    sandbox.routine()


if __name__ == "__main__":
    main()
