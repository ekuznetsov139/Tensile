/*******************************************************************************
 * Cobalt Benchmark
 ******************************************************************************/

#include "Cobalt.h"
#include "Tools.h"
#include "CobaltSolutionCandidates.h"



/*******************************************************************************
 * timeSolution
 ******************************************************************************/
double timeSolution(
    CobaltSolution *solution,
    CobaltTensorData tensorDataC,
    CobaltTensorData tensorDataA,
    CobaltTensorData tensorDataB,
    CobaltControl &ctrl) {

  size_t numEnqueuesPerSample = 6;
  const size_t numSamples = 5;

  double sampleTimes[numSamples];
  Timer timer;

  for ( size_t sampleIdx = 0; sampleIdx < numSamples; sampleIdx++) {

    // start timer
    timer.start();
    for (size_t i = 0; i < numEnqueuesPerSample; i++) {
      cobaltEnqueueSolution(
          solution,
          tensorDataC,
          tensorDataA,
          tensorDataB,
          &ctrl );
    }
    // wait for queue
    // stop timer
    float time = (float)timer.elapsed();
    sampleTimes[sampleIdx] = time;
  } // samples

  // for median, sort and take middle

}

/*******************************************************************************
 * main
 ******************************************************************************/
int main( void ) {

  // creat CobaltControl
  CobaltControl ctrl;

  CobaltTensorData tensorDataC;
  CobaltTensorData tensorDataA;
  CobaltTensorData tensorDataB;

  // initialize Candidates
  initializeSolutionCandidates();

  size_t problemStartIdx = 0;
  size_t problemEndIdx = 0;
  size_t solutionStartIdx = 0;
  size_t solutionEndIdx;

  // for each problem
  for ( size_t problemIdx = problemStartIdx; problemIdx < problemEndIdx;
      problemIdx++ ) {

    solutionEndIdx = numSolutionsPerProblem[problemIdx];
    for ( size_t solutionIdx = solutionStartIdx; solutionIdx < solutionEndIdx;
        solutionIdx++ ) {

      // get solution candidate
      CobaltSolution *solution = solutionCandidates[ solutionIdx ];

      // time solution
      timeSolution( solution, tensorDataC, tensorDataA, tensorDataB, ctrl );

      // write time to result xml file

    } // solution loop

    solutionStartIdx = solutionEndIdx;
    
  } // problem loop

  return 0;
}



