from .celery_config import app
from kwola.components.environments.WebEnvironment import WebEnvironment
from kwola.models.actions.ClickTapAction import ClickTapAction
from kwola.models.TestingSequenceModel import TestingSequenceModel
from .RunTrainingStep import runTrainingStep
from .RunTestingSequence import runTestingSequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor, as_completed, wait
import time

def runRandomInitialization():
    print("Starting random testing sequences for initialization")

    # Seed the pot with 10 random sequences
    numInitializationSequences = 10
    numWorkers = 2

    futures = []
    with ProcessPoolExecutor(max_workers=numWorkers) as executor:
        for n in range(numInitializationSequences):
            sequence = TestingSequenceModel()
            sequence.save()

            future = executor.submit(runTestingSequence, str(sequence.id), True)
            futures.append(future)

            # Add in a delay for each successive task so that they parallelize smoother
            # without fighting for CPU during the startup of that task
            time.sleep(3)

        for future in as_completed(futures[:int(numInitializationSequences/2)]):
            result = future.result()
            print("Random Testing Sequence Completed")

    print("Random initialization completed")


def runMainTrainingLoop():
    sequencesNeeded = 1000
    sequencesCompleted = 0
    numTestSequencesPerTrainingStep = 1
    with ProcessPoolExecutor(max_workers=2) as executor:
        while sequencesCompleted < sequencesNeeded:
            futures = []

            trainingFuture = executor.submit(runTrainingStep)
            futures.append(trainingFuture)

            for testingSequences in range(numTestSequencesPerTrainingStep):
                sequence = TestingSequenceModel()
                sequence.save()
                testingSequenceFuture = executor.submit(runTestingSequence, str(sequence.id), False)
                futures.append(testingSequenceFuture)

            wait(futures)

            print("Completed one parallel training loop! Hooray!")

            sequencesCompleted += 1


@app.task
def trainAgent():
    # runRandomInitialization()
    runMainTrainingLoop()



if __name__ == "__main__":
    trainAgent()
