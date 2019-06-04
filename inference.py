'''
Code to generate accompaniments.

Uses a trained surrogate encoder and a pretrained decoder to perform inference.

Functions
---------
generate_accompaniments() : [NoteSequence]
    Generate accompaniment for a list of sequences.

Examples
--------
```
model = keras.models.load_model(...)
inputs = [
    './data/lmd_clean/raw/Michael Jackson/Beat It.mid',
    './data/lmd_clean/raw/Black Sabbath/Iron Man.mid'
]
accompaniments = generate_accompaniments(inputs, model)
```
'''


import os
from copy import deepcopy

import numpy as np
import magenta.music as mm
from magenta.models.music_vae import configs, trained_model
from magenta.music.sequences_lib import concatenate_sequences

from constants import (MUSICVAE_MODEL_NAME, MUSICVAE_MODEL_PATH, DIM_MELODY)
from utils import (strip_to_melody, remove_melody)


def generate_accompaniments(_sequences, surrogate_encoder, musicvae=None,
                            stitch=True, extract_melody=False,
                            remove_controls=False, temperature=0.1):
    '''
    Generate accompaniment for a collection of input sequences.

    Parameters
    ----------
    sequences : [str path to midi or NoteSequence]
        The input sequences.
    surrogate_encoder : keras Model
        The model to map melodies to latent vectors.
    musicvae : None or Magenta MusicVAE (optional)
        The MusicVAE to use for decoding.
        If None, loads the default MusicVAE.
        NOTE: For quickly performing inference on multiple input batches,
        preload the default MusicVAE outside this function and pass it in.
    stitch : bool (optional)
        Whether to stitch in the original melody or leave the decoded sequence.
    extract_melody : bool (optional)
        Whether to treat the input as a trio and extract the melody.
    remove_controls : bool (optional)
        Whether to delete tempo changes, time changes, etc from the base midi.
    temperature : float (optional)
        Temperature to use in the trio decoder.

    Returns
    -------
    [NoteSequence]
        The input sequences along with generated accompaniment.
    '''

    config = configs.CONFIG_MAP[MUSICVAE_MODEL_NAME]

    musicvae = musicvae or trained_model.TrainedModel(
        config, batch_size=16,
        checkpoint_dir_or_path=os.path.join(MUSICVAE_MODEL_PATH,
                                            MUSICVAE_MODEL_NAME + '.ckpt')
    )

    sequences = deepcopy(_sequences)
    melodies = []

    for (i, seq) in enumerate(sequences):
        if isinstance(seq, str):
            midi = None
            with open(seq, 'rb') as midi_file:
                midi = midi_file.read()
            seq = mm.midi_to_sequence_proto(midi)

        if remove_controls:
            del seq.tempos[1:]
            del seq.time_signatures[1:]
            del seq.control_changes[1:]
#             del seq.tempos[0:]
#             del seq.time_signatures[0:]
#             del seq.control_changes[0:]

        if extract_melody:
            seq = strip_to_melody(seq)

#         melody_tensor = config.data_converter._melody_converter.to_tensors(seq).outputs
        
        # Convert the sequence to tensors, and then strip out just the melody.
        trio_tensors  = config.data_converter.to_tensors(seq).outputs
        melody_tensors = np.array(list(map(lambda t: t[:, :DIM_MELODY],
                                       trio_tensors)))

        # Pad sequence to length 256 (16 beats) if its too small (batch size of 1)
        if melody_tensors.shape[0] == 1:
            pad = max(0, 256 - melody_tensors[0].shape[0])
            melody_tensors[0] = np.pad(melody_tensors[0], [(0, pad), (0, 0)], 'constant')
        melodies.append(melody_tensors)
        
        # Save the modified sequence
        sequences[i] = seq

    # Get the latent representation of just the melody using our trained model
    latent_codes = [surrogate_encoder.predict([melody]) for melody in melodies]
    
    # Decode the latent representation of the melody into 3 parts using Trio
    # Note that this returns an array of different, related musical sections.
    # We use concatenate_sequences to combine them all into one longer piece.
    decoded_sequences = [concatenate_sequences(
                            musicvae.decode(latent_code, 
                                            #length=64,
                                            temperature=temperature)
                         )
                         for latent_code in latent_codes]

    out_sequences = []
    
    # Stitch the original melody and the new accompaniment together.
    if stitch:
        for input_melody, accompaniment in zip(sequences, decoded_sequences):
            # Take the accompaniment from `accompaniment` and the melody from `input_melody`
            out = remove_melody(accompaniment)
            recombined_seq = strip_to_melody(input_melody)
            out.MergeFrom(recombined_seq)
#             out.notes.extend(melody.notes)
            out_sequences.append(out)
    else:
        out_sequences = decoded_sequences

    return out_sequences
