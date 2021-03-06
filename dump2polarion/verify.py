# -*- coding: utf-8 -*-
# pylint: disable=logging-format-interpolation
"""
Verifies that data were updated in Polarion.
"""

from __future__ import absolute_import, unicode_literals

import logging
import os
import time

import requests


# pylint: disable=invalid-name
logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT = 600
_DEFAULT_DELAY = 10

_NOT_FINISHED_STATUSES = ('ready', 'running')


class QueueSearch(object):
    """Search for jobs in the completed jobs queue."""

    def __init__(self, session, queue_url):
        self.session = session
        self.queue_url = queue_url
        self.skip = False
        self._check_setup()

    def _check_setup(self):
        """Checks that all the data that is needed for submit verification is available."""
        if not self.queue_url:
            logger.error(
                'The queue url is not configured, skipping submit verification')
            self.skip = True
            return

        if not self.session:
            logger.error('Missing requests session, skipping submit verification')
            self.skip = True
            return

    # pylint:disable=inconsistent-return-statements
    def download_queue(self, job_ids):
        """Downloads data of completed jobs."""
        if self.skip:
            return

        url = '{0}?jobtype=completed&jobIds={1}'.format(
            self.queue_url, ','.join(str(x) for x in job_ids))
        try:
            response = self.session.get(
                url,
                headers={'Accept': 'application/json'}
            )
            if response:
                response = response.json()
            else:
                response = None
        # pylint: disable=broad-except
        except Exception as err:
            logger.error(err)
            response = None

        return response

    # pylint:disable=inconsistent-return-statements
    def find_jobs(self, job_ids):
        """Finds the jobs in the completed job queue."""
        if self.skip:
            return

        json_data = self.download_queue(job_ids)
        if not json_data:
            return

        jobs = json_data['jobs']
        matched_jobs = []
        for job in jobs:
            if (job.get('id') in job_ids and
                    job.get('status', '').lower() not in _NOT_FINISHED_STATUSES):
                matched_jobs.append(job)

        return matched_jobs

    def wait_for_jobs(self, job_ids, timeout=_DEFAULT_TIMEOUT, delay=_DEFAULT_DELAY):
        """Waits until the jobs appears in the completed job queue."""
        if self.skip:
            return

        logger.debug(
            'Waiting up to {} sec for completion of the job IDs {}'.format(timeout, job_ids))

        remaining_job_ids = set(job_ids)
        found_jobs = []

        countdown = timeout
        while countdown > 0:
            matched_jobs = self.find_jobs(remaining_job_ids)
            if matched_jobs:
                remaining_job_ids.difference_update({job['id'] for job in matched_jobs})
                found_jobs.extend(matched_jobs)
            if not remaining_job_ids:
                return found_jobs
            time.sleep(delay)
            countdown -= delay

        logger.error(
            'Timed out while waiting for completion of the job IDs {}. '
            'Results not updated.'.format(remaining_job_ids))

    # pylint: disable=no-self-use
    def _check_outcome(self, jobs):
        """Parses returned messages and checks submit outcome."""
        if self.skip:
            return False

        if not jobs:
            logger.error('Import failed!')
            return False

        failed_jobs = []
        for job in jobs:
            status = job.get('status')
            if not status:
                failed_jobs.append(job)
                continue

            if status.lower() != 'success':
                failed_jobs.append(job)

        for job in failed_jobs:
            logger.error('job: {0}; status: {1}'.format(job.get('id'), job.get('status')))
        if len(failed_jobs) == len(jobs):
            logger.error('Import failed!')
        elif failed_jobs:
            logger.error('Some import jobs failed!')
        else:
            logger.info('Results successfully updated!')

        return not failed_jobs

    # pylint: disable=no-self-use
    def _download_log(self, url, output_file):
        """Saves log returned by the message bus."""
        logger.info("Saving log {} to {}".format(url, output_file))

        def _do_log_download():
            try:
                return requests.get(url)
            # pylint: disable=broad-except
            except Exception as err:
                logger.error(err)

        # log file may not be ready yet, wait a bit
        for __ in range(5):
            log_data = _do_log_download()
            if log_data or log_data is None:
                break
            time.sleep(2)

        if not log_data:
            logger.error("Failed to download log file '{}'.".format(url))
            return
        with open(os.path.expanduser(output_file), 'ab') as out:
            out.write(log_data.content)

    def get_logs(self, jobs, log_file=None):
        """Get log or log url of the jobs."""
        if not jobs:
            return

        for job in jobs:
            url = job.get('logstashURL')
            if url:
                if log_file:
                    self._download_log(url, log_file)
                else:
                    logger.info('Submit log for job {0}: {1}'.format(job.get('id'), url))

    def verify_submit(self, job_ids, timeout=_DEFAULT_TIMEOUT, delay=_DEFAULT_DELAY, **kwargs):
        """Verifies that the results were successfully submitted."""
        if self.skip:
            return False

        jobs = self.wait_for_jobs(job_ids, timeout, delay)
        self.get_logs(jobs, log_file=kwargs.get('log_file'))

        return self._check_outcome(jobs)


def verify_submit(
        session, queue_url, job_ids, timeout=_DEFAULT_TIMEOUT, delay=_DEFAULT_DELAY, **kwargs):
    """Verifies that the results were successfully submitted."""
    verification_queue = QueueSearch(session=session, queue_url=queue_url)
    return verification_queue.verify_submit(job_ids, timeout=timeout, delay=delay, **kwargs)
