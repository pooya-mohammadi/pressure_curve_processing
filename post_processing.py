import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import os
from loguru import logger


class PostProcessing:
    def __init__(self, input_dir, output_dir):
        self.ifr_df = pd.DataFrame()
        # initialize an empty dataframe with predefined columns
        self.result_df = pd.DataFrame(
            columns=[
                'patient_id',
                'iFR_mean_rest',
                'mid_systolic_ratio_mean_rest',
                'pdpa_mean_rest',
                'iFR_mean_ado',
                'mid_systolic_ratio_mean_ado',
                'pdpa_mean_ado',
                'iFR_mean_dobu',
                'mid_systolic_ratio_mean_dobu',
                'pdpa_mean_dobu',
            ]
        )
        self.output_dir = output_dir
        self.output_file = os.path.join(output_dir, 'results.xlsx')
        # Ensure the output directory exists
        os.makedirs(output_dir, exist_ok=True)
        # write empty dataframe to an excel file with the output path
        self.result_df.to_excel(self.output_file, index=False)
        self.input_dir = input_dir

    def __call__(self):
        for subdir, dirs, files in os.walk(self.input_dir):
            # Skip the root directory itself
            if subdir == self.input_dir:
                continue
            # Process only CSV files in the subdirectories
            for file in files:
                if file.endswith('.csv'):
                    file_path = os.path.join(subdir, file)
                    self.process_file(file_path)

    def process_file(self, file_path):
        data = pd.read_csv(file_path)
        file_name = os.path.basename(file_path).split('.')[0]
        output_dir = os.path.dirname(file_path)

        # Generate plots and save them
        self.plot_average_curve(data, file_name, output_dir)

        # Extract measurements and update results_df
        self.update_results_df(data, file_name)

    def update_results_df(self, data, file_name):
        name = 'rest' if 'rest' in file_name else 'ado' if 'ade' in file_name else 'dobu'
        iFR_mean, mid_systolic_ratio_mean, pdpa_mean, *_ = self.get_measurements(data)
        
        new_row = {
            'patient_id': file_name,
            f'iFR_mean_{name}': iFR_mean,
            f'mid_systolic_ratio_mean_{name}': mid_systolic_ratio_mean,
            f'pdpa_mean_{name}': pdpa_mean,
        }
        
        self.result_df = pd.concat([self.result_df, pd.DataFrame([new_row])], ignore_index=True)
        self.result_df.to_excel(self.output_file, index=False)

    def get_average_curve_between_diastolic_peaks(self, ifr_df, signal='p_aortic_smooth', num_points=100):
        """
        Computes the average curve between diastolic peaks by scaling each interval to the same time length.

        Parameters:
        - ifr_df (pd.DataFrame): The DataFrame containing the signal and peak information.
        - signal (str): The column name of the input signal to analyze.
        - num_points (int): The number of points to normalize each interval to.

        Returns:
        - avg_curve (np.ndarray): The average curve of the signal.
        - avg_time (np.ndarray): The normalized time axis corresponding to the average curve.
        """
        # Extract indices of diastolic peaks
        diastolic_indices = ifr_df.index[ifr_df['peaks'] == 2].tolist()

        if len(diastolic_indices) < 2:
            raise ValueError("Not enough diastolic peaks to calculate intervals.")

        # Initialize a list to store all rescaled intervals
        rescaled_curves = []

        for i in range(len(diastolic_indices) - 1):
            start_idx = diastolic_indices[i]
            end_idx = diastolic_indices[i + 1]

            # Extract the interval data
            interval_data = ifr_df.loc[start_idx:end_idx, signal].values

            if len(interval_data) < 2:
                # Skip intervals with insufficient data
                continue

            # Rescale the interval to have `num_points` using interpolation
            original_time = np.linspace(0, 1, len(interval_data))
            scaled_time = np.linspace(0, 1, num_points)
            rescaled_curve = np.interp(scaled_time, original_time, interval_data)

            rescaled_curves.append(rescaled_curve)

        if len(rescaled_curves) == 0:
            raise ValueError("No valid intervals found for averaging.")

        # Convert the list of rescaled curves to a 2D NumPy array
        rescaled_curves = np.array(rescaled_curves)

        # Compute the average curve across all rescaled intervals
        avg_curve = np.mean(rescaled_curves, axis=0)
        avg_time = np.linspace(0, 1, num_points)

        return avg_time, avg_curve

    def split_df_by_pdpa(self, data):
        """
        Splits the input DataFrame into two separate DataFrames based on the pd/pa ratio.
        """
        if len(data) < 1000:
            logger.warning("Not enough data to split by low and high pd/pa ratio.")
            return data.copy(), data.copy()

        df_copy = data.copy()

        # get lower 25% of pd/pa ratio
        lower_bound = df_copy['pd/pa'].quantile(0.25)
        upper_bound = df_copy['pd/pa'].quantile(0.75)

        df_low = df_copy[df_copy['pd/pa'] < lower_bound]
        df_high = df_copy[df_copy['pd/pa'] > upper_bound]
        
        return df_low, df_high

    def get_measurements(self, data):
        """
        Extracts iFR, mid_systolic_ratio and calculates mean, plus mean of pd/pa ratio.
        For diastolic_ratio and aortic_ratio, gets their start and end time within the cardiac cycle.
        """
        df_copy = data.copy()

        # Get the mean of iFR, mid_systolic_ratio, and pd/pa
        iFR_mean = df_copy['iFR'].mean()
        mid_systolic_ratio_mean = df_copy['mid_systolic_ratio'].mean()
        pdpa_mean = df_copy['pd/pa'].mean()

        # Get the start and end time of diastolic_ratio and aortic_ratio
        diastolic_indices = df_copy.index[df_copy['peaks'] == 2].tolist()

        if len(diastolic_indices) < 2:
            raise ValueError("Not enough diastolic peaks to calculate intervals.")

        # Initialize a list to store all rescaled intervals
        start_time_aortic = []
        end_time_aortic = []
        start_time_diastolic = []
        end_time_diastolic = []

        for i in range(len(diastolic_indices) - 1):
            start_idx = diastolic_indices[i]
            end_idx = diastolic_indices[i + 1]

            start_t = df_copy.loc[start_idx, 'time']
            end_t = df_copy.loc[end_idx, 'time']
            time_range = end_t - start_t

            # Extract the interval data for aortic_ratio
            interval_data = df_copy.loc[start_idx:end_idx, 'aortic_ratio']

            # Find the first and last non-NaN indices
            first_valid_idx = interval_data.first_valid_index()
            last_valid_idx = interval_data.last_valid_index()

            if first_valid_idx is not None:
                # Normalize the time of the first valid value
                first_time = df_copy.loc[first_valid_idx, 'time']
                normalized_start = (first_time - start_t) / time_range
                start_time_aortic.append(normalized_start)

            if last_valid_idx is not None:
                # Normalize the time of the last valid value
                last_time = df_copy.loc[last_valid_idx, 'time']
                normalized_end = (last_time - start_t) / time_range
                end_time_aortic.append(normalized_end)

            # Repeat the same process for diastolic_ratio
            interval_data = df_copy.loc[start_idx:end_idx, 'diastolic_ratio']

            first_valid_idx = interval_data.first_valid_index()
            last_valid_idx = interval_data.last_valid_index()

            if first_valid_idx is not None:
                first_time = df_copy.loc[first_valid_idx, 'time']
                normalized_start = (first_time - start_t) / time_range
                start_time_diastolic.append(normalized_start)

            if last_valid_idx is not None:
                last_time = df_copy.loc[last_valid_idx, 'time']
                normalized_end = (last_time - start_t) / time_range
                end_time_diastolic.append(normalized_end)

        start_time_aortic_mean = np.mean(start_time_aortic)
        end_time_aortic_mean = np.mean(end_time_aortic)
        start_time_diastolic_mean = np.mean(start_time_diastolic)
        end_time_diastolic_mean = np.mean(end_time_diastolic)

        return (
            iFR_mean,
            mid_systolic_ratio_mean,
            pdpa_mean,
            start_time_aortic_mean,
            end_time_aortic_mean,
            start_time_diastolic_mean,
            end_time_diastolic_mean,
        )

    def plot_average_curve(self, data, file_name, output_dir):
        """
        Plots the average curve between diastolic peaks for `p_aortic_smooth` and `p_distal_smooth`
        for all data, low `pd/pa`, and high `pd/pa` groups. Saves three plots.
        """
        name = 'rest' if 'rest' in file_name else 'ado' if 'ade' in file_name else 'dobu'
        data = data.copy()

        # Split the data into low and high pd/pa groups
        data_lower, data_higher = self.split_df_by_pdpa(data)

        # Define the groups to process
        groups = {
            'all': data,
            'low': data_lower,
            'high': data_higher
        }

        for group_name, group_data in groups.items():
            # Calculate average curves
            avg_time, avg_curve_aortic = self.get_average_curve_between_diastolic_peaks(group_data, signal='p_aortic_smooth', num_points=100)
            _, avg_curve_distal = self.get_average_curve_between_diastolic_peaks(group_data, signal='p_distal_smooth', num_points=100)

            # Get measurements
            (
                iFR_mean,
                mid_systolic_ratio_mean,
                pdpa_mean,
                start_time_aortic_mean,
                end_time_aortic_mean,
                start_time_diastolic_mean,
                end_time_diastolic_mean,
            ) = self.get_measurements(group_data)

            # Plot the results
            plt.figure(figsize=(10, 6))
            plt.plot(avg_time, avg_curve_aortic, label='p_aortic_smooth', color='blue')
            plt.plot(avg_time, avg_curve_distal, label='p_distal_smooth', color='green')
            plt.axvline(x=start_time_aortic_mean, color='red', linestyle='--', label='Aortic Start/End')
            plt.axvline(x=end_time_aortic_mean, color='red', linestyle='--')
            plt.axvline(x=start_time_diastolic_mean, color='blue', linestyle='--', label='Diastolic Start/End')
            plt.axvline(x=end_time_diastolic_mean, color='blue', linestyle='--')
            plt.text(
                0.5,
                0.9,
                f'iFR: {iFR_mean:.2f}',
                horizontalalignment='center',
                verticalalignment='center',
                transform=plt.gca().transAxes,
            )
            plt.text(
                0.5,
                0.85,
                f'mid_systolic_ratio: {mid_systolic_ratio_mean:.2f}',
                horizontalalignment='center',
                verticalalignment='center',
                transform=plt.gca().transAxes,
            )
            plt.text(
                0.5,
                0.8,
                f'pd/pa: {pdpa_mean:.2f}',
                horizontalalignment='center',
                verticalalignment='center',
                transform=plt.gca().transAxes,
            )
            plt.xlabel('Time')
            plt.ylabel('Pressure')
            plt.title(f'Average Curve between Diastolic Peaks ({name.capitalize()} - {group_name.capitalize()})')
            plt.legend()
            
            # Save the plot in the same directory as the CSV file
            plot_filename = os.path.join(output_dir, f"{file_name}_average_curve_{group_name}.png")
            plt.savefig(plot_filename)
            plt.close()  # Close the plot to free up memory