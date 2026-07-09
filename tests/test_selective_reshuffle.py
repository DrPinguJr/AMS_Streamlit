import unittest

import pandas as pd

from Flexar.BlueSG.vehicle_route_optimizer import (
    RiderState,
    build_jobs_by_stable_id,
    find_best_selective_reshuffle,
    rebuild_outputs_from_sequences,
    stable_job_id_from_job,
)


def make_job(index, plate, pickup, dropoff):
    return {
        "_original_order": index,
        "Car Plate": plate,
        "Pickup Address": pickup,
        "Pickup Lot": f"L{index}",
        "Drop-off Address": dropoff,
    }


class SelectiveReshuffleTests(unittest.TestCase):
    def setUp(self):
        self.jobs = [
            make_job(0, "ELT1", "Yishun", "Woodlands"),
            make_job(1, "LES1", "Tampines", "Bedok"),
            make_job(2, "SAF1", "Jurong", "Clementi"),
            make_job(3, "SMS4154J", "Sengkang", "Punggol"),
            make_job(4, "SPE9011T", "Punggol", "Hougang"),
            make_job(5, "SLP8094A", "Hougang", "Tampines"),
            make_job(6, "SMA6210L", "Tampines", "Simei"),
            make_job(7, "SNU3954B", "Simei", "Bedok"),
            make_job(8, "SNH6184E", "Bedok", "Hougang"),
        ]
        self.jobs_df = pd.DataFrame(self.jobs)
        self.jobs_by_id = build_jobs_by_stable_id(self.jobs_df)
        self.ids = {job["Car Plate"]: stable_job_id_from_job(job) for job in self.jobs}
        self.riders = [
            RiderState("El-Tian", "Yishun", "North"),
            RiderState("Lester", "Tampines", "East"),
            RiderState("Safuwan", "Jurong", "West"),
            RiderState("Sadiq", "Sengkang", "North-East"),
            RiderState("Zhi Ming", "Tampines", "East"),
            RiderState("Michael", "Ang Mo Kio", "Central"),
            RiderState("Jayson", "Paya Lebar", "East"),
        ]
        self.sequences = {
            "El-Tian": [self.ids["ELT1"]],
            "Lester": [self.ids["LES1"]],
            "Safuwan": [self.ids["SAF1"]],
            "Sadiq": [self.ids["SMS4154J"], self.ids["SPE9011T"], self.ids["SLP8094A"]],
            "Zhi Ming": [self.ids["SMA6210L"], self.ids["SNU3954B"], self.ids["SNH6184E"]],
            "Michael": [],
            "Jayson": [],
        }

    def test_selective_reshuffle_preserves_locked_and_unselected_jobs(self):
        result = find_best_selective_reshuffle(
            self.sequences,
            self.jobs_by_id,
            self.riders,
            jobs_df=self.jobs_df,
            locked_riders={"El-Tian", "Lester", "Safuwan"},
            locked_job_ids={
                self.ids["SMS4154J"],
                self.ids["SPE9011T"],
                self.ids["SMA6210L"],
                self.ids["SNU3954B"],
            },
            reshuffle_job_ids={self.ids["SLP8094A"], self.ids["SNH6184E"]},
            eligible_receiver_riders={"Sadiq", "Zhi Ming", "Michael", "Jayson"},
            use_onemap=False,
            optimise_by="duration",
        )

        self.assertTrue(result["success"], result.get("reason"))
        proposed = result["proposed_sequences"]

        self.assertEqual(proposed["El-Tian"], self.sequences["El-Tian"])
        self.assertEqual(proposed["Lester"], self.sequences["Lester"])
        self.assertEqual(proposed["Safuwan"], self.sequences["Safuwan"])
        self.assertEqual(proposed["Sadiq"][:2], self.sequences["Sadiq"][:2])
        self.assertEqual(proposed["Zhi Ming"][:2], self.sequences["Zhi Ming"][:2])

        all_before = sorted(job_id for jobs in self.sequences.values() for job_id in jobs)
        all_after = sorted(job_id for jobs in proposed.values() for job_id in jobs)
        self.assertEqual(all_after, all_before)

    def test_rebuild_outputs_from_accepted_sequences_keeps_integrity(self):
        route_df, summary_df, warnings = rebuild_outputs_from_sequences(
            self.sequences,
            self.riders,
            self.jobs_by_id,
            jobs_df=self.jobs_df,
            use_onemap=False,
            optimise_by="duration",
        )

        self.assertEqual(len(route_df), len(self.jobs))
        self.assertFalse(summary_df.empty)
        self.assertIsInstance(warnings, list)
        self.assertTrue(route_df["Route Validation Status"].eq("OK").all())


if __name__ == "__main__":
    unittest.main()
