import unittest

from ms_deisotope import processor
from ms_deisotope.averagine import glycopeptide
from ms_deisotope.scoring import PenalizedMSDeconVFitter

from ms_deisotope.test.common import datafile


class TestScanProcessor(unittest.TestCase):
    mzml_path = datafile("three_test_scans.mzML")
    missing_charge_mzml = datafile("has_missing_charge_state_info.mzML")

    def test_processor(self):
        proc = processor.ScanProcessor(self.mzml_path, ms1_deconvolution_args={
            "averagine": glycopeptide,
            "scorer": PenalizedMSDeconVFitter(5., 2.)
        })
        for scan_bunch in iter(proc):
            self.assertIsNotNone(scan_bunch)
            self.assertIsNotNone(scan_bunch.precursor)
            self.assertIsNotNone(scan_bunch.products)

    def test_averaging_processor(self):
        proc = processor.ScanProcessor(self.mzml_path, ms1_deconvolution_args={
            "averagine": glycopeptide,
            "scorer": PenalizedMSDeconVFitter(5., 2.)
        }, ms1_averaging=1)
        for scan_bunch in iter(proc):
            self.assertIsNotNone(scan_bunch)
            self.assertIsNotNone(scan_bunch.precursor)
            self.assertIsNotNone(scan_bunch.products)

    def test_missing_charge_processing(self):
        proc = processor.ScanProcessor(self.missing_charge_mzml, ms1_deconvolution_args={
            "averagine": glycopeptide,
            "scorer": PenalizedMSDeconVFitter(5., 2.)
        })
        for scan_bunch in iter(proc):
            self.assertIsNotNone(scan_bunch)
            self.assertIsNotNone(scan_bunch.precursor)
            self.assertIsNotNone(scan_bunch.products)


if __name__ == '__main__':
    unittest.main()
