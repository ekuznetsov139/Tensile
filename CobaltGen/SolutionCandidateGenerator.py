import copy
import Structs
import FileReader
import KernelWriter
import SolutionWriter
import argparse


################################################################################
# SolutionCandidateGenerator
################################################################################
class SolutionCandidateGenerator:

  # limit work-group size to boost occupancy
  maxLocalMemoryBytes = 32768
  localMemPad = 1
  maxRegisters = 16*16*( 4*4*4 + 4*4 + 4*4 )

  # problem is skinny if smaller dim < 32 and larger dim > 4096
  skinnyThresholds = [32, 4096]

  # tile for non-skinny problem must be square: tile1/tile0 <= 1
  # tile for skinny problem must be tile1/tile0 <= 16*2
  skinnyRatioWorkGroup = [ 1, 16] # verified against 8xHuge system
  skinnyRatioMicroTile = [ 1, 2] # verified against 8xHuge system
  skinnyRatioMacroTile = [ skinnyRatioWorkGroup[0]*skinnyRatioMicroTile[0], \
      skinnyRatioWorkGroup[1]*skinnyRatioMicroTile[1] ]
  minMicroTileSize = 4
  maxMicroTileSize = 8
  unrollLevels = [32, 16, 8, 4, 2, 1]
  #unrollLevels = [16]
  universeUnroll = { \
       1: [ [  1 ], [ 32, 1 ], [ 16, 1 ], [  8, 1 ] ], \
       2: [ [  2 ], [ 32, 2 ], [ 16, 2 ], [  8, 2 ] ], \
       4: [ [  4 ], [ 32, 4 ], [ 16, 4 ], [  8, 4 ] ], \
       8: [ [  8 ], [ 32, 8 ], [ 16, 8 ], [ 4 ] ], \
      16: [ [ 16 ], [ 8 ], [ 4 ] ], \
      32: [ [ 32 ], [ 16 ], [ 8 ], [ 4 ] ] \
      }
  """
  unrollLevels = [1]
  universeUnroll = {  1: [ [ 4, 1 ] ] }
  """
  # preprocessor define (0) leading strides, (1) offsets, (2) everything
  # if problem conflicts with optimization level, generator reverts optimization level below

  """
  ppdUniverse = [ \
      [ True,  True,  True], \
      [False, False, False], \
      [ True,  True, False], \
      [ True, False, False], \
      [False,  True, False], \
      ]
  """
  # opencl and hip now require offsets
  ppdUniverse = [ \
      [ True,  False, False], \
      ]
  # non-skinny problem will only choose from 8x8 and 16x16
  """
  universeWorkGroupDim = [ \
      [4,16],  [8,8],  [16,4], \
      [4,32], [8,16],  [16,8], [32,4], \
      [4,48],  [6,32], [8,24], [12,16], [16, 12], [24,8], [32,6], [48,4], \
      [4,64], [8,32], [16,16], [32,8],  [64,4] ]
  """
  universeWorkGroupDim = [ [16,16] ]

  # removed non-branch type
  universeBranch = [ Structs.BranchType(1), Structs.BranchType(2) ]

  # for research, =True means don't generate any solution requiring branches, i.e., only generate fastest
  noBranches = False

  ##############################################################################
  # init
  ##############################################################################
  def __init__(self, optimizeAlpha, optimizeBeta, backend):
    self.optimizeAlpha = optimizeAlpha
    self.optimizeBeta = optimizeBeta
    self.backend = backend
    if self.backend.isHIP():
      # remove optimizations so that all kernels have identical arguments
      self.ppdUniverse = [ [True, False, False] ]
    self.kernelWriter = KernelWriter.KernelWriter(backend)
    self.solutionWriter = SolutionWriter.SolutionWriter(backend)

  ##############################################################################
  # getSolutionCandidatesForProblem
  ##############################################################################
  def getSolutionCandidatesForProblem( self, inputProblem ):
    problem = copy.deepcopy(inputProblem)

    # optimize alpha and beta?
    if not self.optimizeAlpha and not problem.operation.useAlpha():
      problem.operation.alphaType = problem.tensorC.dataType
    if not self.optimizeBeta and not problem.operation.useBeta():
      problem.operation.betaType = problem.tensorC.dataType

    numIndicesC = len(problem.tensorC.dimensions)
    numIndicesA = len(problem.tensorA.dimensions)
    numIndicesB = len(problem.tensorB.dimensions)

    # create solution object
    kernel = Structs.Kernel()
    solution = Structs.Solution()
    solutionCandidates = []

    # Solution Correctness Parameters
    #kernel.operation = problem.operation
    kernel.dataTypeC = problem.tensorC.dataType
    kernel.dataTypeA = problem.tensorA.dataType
    kernel.dataTypeB = problem.tensorB.dataType
    kernel.problem = problem

    # Index Assignments
    kernel.indexOrderC = []
    kernel.indexOrderSummation = []
    makeIndexAssignments( kernel, problem )
    #kernel.indexAssignmentDim0 = kernel.indexOrderC[ \
    #    numIndicesC - 2 ]
    #kernel.indexAssignmentDim1 = kernel.indexOrderC[ \
    #    numIndicesC - 1 ]

    # Problem Characteristics affecting performance
    problemSizeDim0 = problem.tensorC.dimensions[ \
        kernel.indexAssignmentDim0].size
    problemSizeDim1 = problem.tensorC.dimensions[ \
        kernel.indexAssignmentDim1].size
    problemSkinnyDim0 = 0 # false
    # size < 96 begins to behave skinny, i.e., becomes bandwidth bound
    # but only < 32 does a unique tile improve performance;
    # for sizes 32-96 square tiles are still withing 4% performance of best skinny
    if problemSizeDim0 < 32 and problemSizeDim1 > 1024:
      problemSkinnyDim0 = 1
    problemSkinnyDim1 = 0
    if problemSizeDim1 < 32 and problemSizeDim0 > 1024:
      problemSkinnyDim1 = 1
    problemSizeUnroll = -1
    for i in range(len(problem.operation.indexAssignmentsA)):
      if kernel.indexUnroll == problem.operation.indexAssignmentsA[i]:
        problemSizeUnroll = problem.tensorA.dimensions[i].size
        break
    tensorStrideDim0 = -1
    for i in range(len(problem.operation.indexAssignmentsA)):
      if kernel.indexAssignmentDim0 == problem.operation.indexAssignmentsA[i]:
        tensorStrideDim0 = problem.tensorA.dimensions[i].stride
        break
    tensorStrideDim1 = -1
    for i in range(len(problem.operation.indexAssignmentsB)):
      if kernel.indexAssignmentDim1 == problem.operation.indexAssignmentsB[i]:
        tensorStrideDim1 = problem.tensorA.dimensions[i].stride
        break

    # only try the highest unroll level
    selectedUnroll = -1
    for unroll in self.unrollLevels:
      if problemSizeUnroll % unroll == 0:
        selectedUnroll = unroll
        break

    # for all unroll combinations of selected unroll level
    for unroll in self.universeUnroll[selectedUnroll]:
      kernel.unrolls = unroll
      # summation must be multiple of last unroll
      if problemSizeUnroll % unroll[len(unroll)-1] > 0:
        continue
      # first do-while summation loop has to do at least one iteration
      if problemSizeUnroll < unroll[0]:
        continue
      # second do-while summation loop has to do at least one iteration
      if len(unroll) > 1:
        if problemSizeUnroll % unroll[0] < unroll[1]:
          continue
      for workGroup in self.universeWorkGroupDim:
        kernel.tile.workGroup = workGroup
        # only try skinny work-group if problem is skinny
        if float(workGroup[1])/workGroup[0] \
            > self.skinnyRatioWorkGroup[problemSkinnyDim0]:
          continue
        if float(workGroup[0])/workGroup[1] \
            > self.skinnyRatioWorkGroup[problemSkinnyDim1]:
          continue
        # for all micro-tile dimensions
        for microTileDim0 in range(self.minMicroTileSize, \
            self.maxMicroTileSize+1):
          for microTileDim1 in range(self.minMicroTileSize, \
              self.maxMicroTileSize+1):
            microTile = [ microTileDim0, microTileDim1 ]
            kernel.tile.microTile = microTile
            # only try skinny micro-tile if problem is skinny
            if float(microTile[1])/microTile[0] \
                > self.skinnyRatioMicroTile[problemSkinnyDim0]:
              continue
            if float(microTile[0])/microTile[1] \
                > self.skinnyRatioMicroTile[problemSkinnyDim1]:
              continue
            # only try skinny macro-tile if problem is skinny
            macroTileDim0 = workGroup[0] * microTile[0]
            macroTileDim1 = workGroup[1] * microTile[1]
            if float(macroTileDim1)/macroTileDim0 \
                > self.skinnyRatioMacroTile[problemSkinnyDim0]:
              continue
            if float(macroTileDim0)/macroTileDim1 \
                > self.skinnyRatioMacroTile[problemSkinnyDim1]:
              continue
            # macro-tile not too large
            numWorkItems = workGroup[0] * workGroup[1]
            numRegisters = numWorkItems * ( microTile[0] * microTile[1] \
                * kernel.dataTypeC.numRegisters() \
                + microTile[0] * kernel.dataTypeA.numRegisters() \
                + microTile[1] * kernel.dataTypeB.numRegisters() )
            if numRegisters > self.maxRegisters:
              continue

            localMemoryBytes = 0
            if kernel.tensorAssignedDim0 == 0: # dim0 in tesnsorA
              localMemoryBytes = unroll[0] * ((macroTileDim0+self.localMemPad)*kernel.dataTypeA.numBytes() + (macroTileDim1+self.localMemPad)*kernel.dataTypeB.numBytes())
            else: # dim1 in tensorA
              localMemoryBytes = unroll[0] * ((macroTileDim0+self.localMemPad)*kernel.dataTypeB.numBytes() + (macroTileDim1+self.localMemPad)*kernel.dataTypeA.numBytes())
            if localMemoryBytes > self.maxLocalMemoryBytes:
              #print "%u = %u * ( %u*%u + %u*%u)\n" % (localMemoryBytes, unroll[0], macroTileDim0, kernel.dataTypeA.numBytes(), macroTileDim1, kernel.dataTypeB.numBytes())
              continue
# 1649 candidates -> 128 ->

            # load grid
            #loadSizeParaA = (workGroup[0]*microTile[0]*unroll[0])
            #loadSizeParaB = (workGroup[1]*microTile[1]*unroll[0])
            #if kernel.unrollDimStrideGreaterThanTileDimStrideA:
            loadSizeParaA = macroTileDim0 if kernel.unrollDimStrideGreaterThanTileDimStrideA else unroll[0];
            loadSizeParaB = macroTileDim1 if not kernel.unrollDimStrideLessThanTileDimStrideB else unroll[0];
            # print loadSizeParaA, loadSizeParaB
            numLoadsA = (workGroup[0]*microTile[0]*unroll[0])/(workGroup[0]*workGroup[1])
            numLoadsB = (workGroup[1]*microTile[1]*unroll[0])/(workGroup[0]*workGroup[1])
            # whole number of loads
            if (workGroup[0]*microTile[0]*unroll[0])%(workGroup[0]*workGroup[1]) > 0:
              continue
            if (workGroup[1]*microTile[1]*unroll[0])%(workGroup[0]*workGroup[1]) > 0:
              continue

            for numLoadsParaA in range(1, numLoadsA+1):
              if numLoadsA % numLoadsParaA > 0:
                continue
              numLoadsPerpA = numLoadsA / numLoadsParaA
              if loadSizeParaA%numLoadsParaA>0:
                continue
              if (workGroup[0]*workGroup[1])%(loadSizeParaA/numLoadsParaA) > 0:
                continue
              #else:
              #  print "%d%%(%d/%d) == 0 (%d)"% (workGroup[0]*workGroup[1],macroTileDim0,numLoadsPerpA,numLoadsA )
              kernel.numLoadsA = numLoadsParaA
              for numLoadsParaB in range(1, numLoadsB+1):
                if numLoadsB % numLoadsParaB > 0:
                  continue
                numLoadsPerpB = numLoadsB / numLoadsParaB
                if loadSizeParaB%numLoadsParaB>0:
                  continue
                if (workGroup[0]*workGroup[1])%(loadSizeParaB/numLoadsParaB) > 0:
                  continue
                kernel.numLoadsB = numLoadsParaB

                # kernel grid
                kernelGrid = [ 1, 1, 1 ]
                if not problemSkinnyDim0 and not problemSkinnyDim1 and \
                    (kernel.unrollDimStride0 % 1024 == 0 or kernel.unrollDimStride1 % 1024 == 0):
                  kernelGrid[0] = kernel.unrollDimStride0 / 2048;
                  kernelGrid[1] = kernel.unrollDimStride1 / 2048;
                  kernelGrid[2] = kernel.unrollDimSize / 1024
                  if kernelGrid[0] == 0:
                    kernelGrid[0]=1
                  if kernelGrid[1] == 0:
                    kernelGrid[1]=1
                  if kernelGrid[2] == 0:
                    kernelGrid[2]=1
                  if kernelGrid[2] > 1 and not kernel.problem.operation.useBeta:
                      kernel.problem.operation.useBeta = True
                      kernel.problem.operation.betaType = problem.tensorC.dataType
                      print "forcing useBeta=True due to mod1024 kernel grid"
                  # print "kernelGrid = {%u, %u, %u}" % ( kernelGrid[0], kernelGrid[1], kernelGrid[2])

                for ppdOptimization in self.ppdUniverse:
                  ppdLeadingStride = ppdOptimization[0]
                  ppdOffsets = ppdOptimization[1]
                  ppdAll = ppdOptimization[2]

                  # if optimization level optimizes away offsets, but problem requires offsets, fix it
                  if ppdOffsets and problem.operation.useOffsets:
                    print "reverting ppdOffsets->False"
                    ppdOffsets = False

                  # if optimization level optimizes away initial strides, but problem uses non-zero initial strides, fix it
                  if ppdLeadingStride and \
                    (  problem.tensorC.dimensions[0].stride != 1 \
                    or problem.tensorA.dimensions[0].stride != 1 \
                    or problem.tensorB.dimensions[0].stride != 1):
                    print "reverting ppdLeadingStride->False"
                    ppdLeadingStride = False

                  # for branch types
                  for branchType in self.universeBranch:
                    solution.kernelGrid = copy.deepcopy(kernelGrid)
                    solution.kernels = []

                    # branch - 1 exact kernel; DEPRECATED
                    #if branchType.isNone():
                    #  if problemSizeDim0 % macroTileDim0 != 0 \
                    #      or problemSizeDim1 % macroTileDim1 != 0:
                    #    continue
                    #  solution.branch = [branchType, branchType]
                    #  kernel.tile.branch = [branchType, branchType ]
                    #  solution.kernels.append( copy.deepcopy(kernel) )
                    leadingStridesOne = False
                    if problem.tensorC.dimensions[0].stride == 1 \
                        and problem.tensorA.dimensions[0].stride == 1 \
                        and problem.tensorB.dimensions[0].stride == 1:
                      leadingStridesOne = True
                    # branch - 2-4 kernels
                    if branchType.isMultiple():
                      if self.noBranches:
                        if problemSizeDim0 % macroTileDim0 != 0 \
                            or problemSizeDim1 % macroTileDim1 != 0:
                          continue

                      solution.branch = [branchType, branchType]
                      if leadingStridesOne:
                        solution.ppdLeadingStride = ppdLeadingStride
                      solution.ppdOffsets = ppdOffsets # kernel 0 need offsets?
                      solution.ppdAll = False # kernels 1-3 will need sizes
                      # add main kernel
                      kernel.tile.branch = [Structs.BranchType(0), Structs.BranchType(0)]
                      if leadingStridesOne:
                        kernel.ppdLeadingStride = ppdLeadingStride
                      kernel.ppdOffsets = ppdOffsets
                      kernel.ppdAll = ppdAll
                      solution.kernels.append( copy.deepcopy(kernel) )
                      # add edge-0 kernel
                      solution.kernelGrid[0] += 1
                      kernel.tile.branch = [ branchType, Structs.BranchType(0) ]
                      if leadingStridesOne:
                        kernel.ppdLeadingStride = ppdLeadingStride
                      kernel.ppdOffsets = False
                      kernel.ppdAll = False
                      solution.kernels.append( copy.deepcopy(kernel) )
                      # add edge-1 kernel
                      solution.kernelGrid[1] += 1
                      kernel.tile.branch = [ Structs.BranchType(0), branchType ]
                      if leadingStridesOne:
                        kernel.ppdLeadingStride = ppdLeadingStride
                      kernel.ppdOffsets = False
                      kernel.ppdAll = False
                      solution.kernels.append( copy.deepcopy(kernel) )
                      # add corner-01 kernel
                      kernel.tile.branch = [ branchType, branchType ]
                      if leadingStridesOne:
                        kernel.ppdLeadingStride = ppdLeadingStride
                      kernel.ppdOffsets = False
                      kernel.ppdAll = False
                      solution.kernels.append( copy.deepcopy(kernel) )

                    # branch - 1 branched kernel
                    elif branchType.isBranched():
                      if problemSizeDim0 % macroTileDim0 == 0 \
                          and problemSizeDim1 % macroTileDim1 == 0:
                        continue
                      if kernelGrid[0] > 1 or kernelGrid[1] > 1 or kernelGrid[2] > 1: # don't use b kernels for 4096 cases b/c already not using single kernel
                        continue
                      if self.noBranches:
                        continue
                      solution.branch = [branchType, branchType]
                      if leadingStridesOne:
                        solution.ppdLeadingStride = ppdLeadingStride
                      solution.ppdOffsets = ppdOffsets
                      solution.ppdAll = ppdAll
                      kernel.tile.branch = [branchType, branchType ]
                      kernel.ppdLeadingStride = ppdLeadingStride
                      kernel.ppdOffsets = ppdOffsets
                      kernel.ppdAll = ppdAll
                      solution.kernels.append( copy.deepcopy(kernel) )
                      solution.kernels.append( None )
                      solution.kernels.append( None )
                      solution.kernels.append( None )

                    # branch - unknown
                    else:
                      print "ERROR - unrecognized branchType"

                    # kernels, grid, and branching specified, now add solution
                    # print solution
                    # print "  " + self.solutionWriter.getName(solution)
                    solutionCandidates.append( copy.deepcopy(solution) )
    return solutionCandidates


################################################################################
# Make Index Assignments
# indicesSummation:
#    largest stride -> shortest stride
# indicesC:
#    batched largest stride (A+B) -> shortest stride
#    free largest stride (of A,B input tensor) -> shortest stride
#    last two indices must belong to different A,B and are assigned d0,d1
################################################################################
def makeIndexAssignments(kernel, problem):
  numIndicesC = problem.operation.numIndicesFree \
      + problem.operation.numIndicesBatch
  numIndicesA = len(problem.operation.indexAssignmentsA)
  numIndicesB = len(problem.operation.indexAssignmentsB)
  # C indices in order of descending stride
  # sort free indices, then append after batched indices
  indicesBatchedUnsorted = []
  indicesFreeUnsorted = []
  for i in range(0,numIndicesC):
    indexIsBatched = False
    if i in problem.operation.indexAssignmentsA:
      if i in problem.operation.indexAssignmentsB:
        indexIsBatched = True
    if indexIsBatched:
      stride = 0
      for j in range(0,numIndicesA):
        if problem.operation.indexAssignmentsA[j] == i:
          stride += problem.tensorA.dimensions[j].stride
        if problem.operation.indexAssignmentsB[j] == i:
          stride += problem.tensorB.dimensions[j].stride
      indicesBatchedUnsorted.append([stride, i])
    else:
      stride = 0
      indexBelongsToTensor = 0
      for j in range(0,numIndicesA):
        if problem.operation.indexAssignmentsA[j] == i:
          stride = problem.tensorA.dimensions[j].stride
          indexBelongsToTensor = 0
        if problem.operation.indexAssignmentsB[j] == i:
          stride = problem.tensorB.dimensions[j].stride
          indexBelongsToTensor = 1
      indicesFreeUnsorted.append( [stride, i, indexBelongsToTensor] )

  indicesBatchedSorted = sorted( indicesBatchedUnsorted, \
      key = lambda x: int(x[0]), reverse=True )
  indicesFreeSorted = sorted( indicesFreeUnsorted, \
      key = lambda x: int(x[0]), reverse=True )
  # if last two free indices belong to same tensor
  if indicesFreeSorted[len(indicesFreeSorted)-1][2] \
      == indicesFreeSorted[len(indicesFreeSorted)-2][2]:
    # look backwards for smallest stride belonging to different tensor
    for i in range(len(indicesFreeSorted)-1, 0):
      if indicesFreeSorted[len(indicesFreeSorted)-1][2] \
          != indicesFreeSorted[i][3]:
        # remove idx i from current location
        tmp = indicesFreeSorted.pop(i)
        # and place it second to last
        indicesFreeSorted.insert(len(indicesFreeSorted)-1,tmp)
  #print indicesFreeSorted

  # the last two indices will be d0,d1; d0 is the one with the shortest C stride
  if problem.tensorC.dimensions[indicesFreeSorted[len(indicesFreeSorted)-1][1]].stride \
      > problem.tensorC.dimensions[indicesFreeSorted[len(indicesFreeSorted)-2][1]].stride: # need to swap
    #print "swapping d0,d1"
    tmp = indicesFreeSorted.pop()
    indicesFreeSorted.insert(len(indicesFreeSorted)-1,tmp)
    #print indicesFreeSorted

  kernel.indexAssignmentDim0 = indicesFreeSorted[len(indicesFreeSorted)-1][1]
  kernel.tensorAssignedDim0 = indicesFreeSorted[len(indicesFreeSorted)-1][2]
  kernel.indexAssignmentDim1 = indicesFreeSorted[len(indicesFreeSorted)-2][1]
  kernel.tensorAssignedDim1 = indicesFreeSorted[len(indicesFreeSorted)-2][2]
  strideD0 = indicesFreeSorted[len(indicesFreeSorted)-1][0]
  strideD1 = indicesFreeSorted[len(indicesFreeSorted)-2][0]
  #print "d0=%u, d1=%u" % (kernel.indexAssignmentDim0, kernel.indexAssignmentDim1)
  #print "strideD0,1 = " + str(strideD0) + ", " + str(strideD1)

  for index in indicesBatchedSorted:
    kernel.indexOrderC.append( index[1] )
  for index in indicesFreeSorted:
    kernel.indexOrderC.append( index[1] )

  # summation indices in order of descending A-stride + B-stride
  indicesSummationUnsorted = []
  for i in range(0,problem.operation.numIndicesSummation):
    sumIndex = i + numIndicesC
    assignmentA = -1
    for j in range(0,numIndicesA):
      if problem.operation.indexAssignmentsA[j] == sumIndex:
        assignmentA = j
    assignmentB = -1
    for j in range(0,numIndicesB):
      if problem.operation.indexAssignmentsB[j] == sumIndex:
        assignmentB = j
    indicesSummationUnsorted.append( \
        [problem.tensorA.dimensions[assignmentA].stride \
        + problem.tensorB.dimensions[assignmentB].stride, i] )
  indicesSummationSorted = sorted( indicesSummationUnsorted, \
      key = lambda x: int(x[0]), reverse=True )
  for i in range(0,len(indicesSummationSorted)):
    kernel.indexOrderSummation.append( indicesSummationSorted[i][1] )


  #unrollDimStride = indicesSummationSorted[len(indicesSummationSorted)-1][0]
  unrollIndex = kernel.indexOrderSummation[len(kernel.indexOrderSummation)-1] + len(problem.tensorC.dimensions)
  kernel.indexUnroll = unrollIndex
  unrollIndexA = problem.operation.indexAssignmentsA.index(unrollIndex)
  unrollIndexB = problem.operation.indexAssignmentsB.index(unrollIndex)
  #print "unrollIndex = " + str(unrollIndex)
  #print "indexAssignmentsA = " + str(problem.operation.indexAssignmentsA)
  #print "indexAssignmentsB = " + str(problem.operation.indexAssignmentsB)
  #print "unrollIndexA,B = " + str(unrollIndexA) + ", " + str(unrollIndexB)
  unrollDimStrideA = problem.tensorA.dimensions[unrollIndexA].stride
  unrollDimStrideB = problem.tensorB.dimensions[unrollIndexB].stride
  kernel.unrollDimSize = problem.tensorA.dimensions[unrollIndexA].size
  #print "unrollStrideA,B = " + str(unrollDimStrideA) + ", " + str(unrollDimStrideB)
  #print "tensorAssignedDim0 = " + ("A" if kernel.tensorAssignedDim0==0 else "B")
  #print "strideD0 = " + str(strideD0)
  #print "strideD1 = " + str(strideD1)

  #kernel.unrollDimStrideGreaterThanTileDimStride0 = \
  #    indicesFreeSorted[len(indicesFreeSorted)-2][0] < unrollDimStride
  #kernel.unrollDimStrideGreaterThanTileDimStride1 = \
  #    indicesFreeSorted[len(indicesFreeSorted)-1][0] < unrollDimStride
  if kernel.tensorAssignedDim0 == 0: # A assigned dim0
    kernel.unrollDimStrideGreaterThanTileDimStrideA = \
      unrollDimStrideA > strideD0
    kernel.unrollDimStrideLessThanTileDimStrideB = \
      unrollDimStrideB < strideD1
    kernel.unrollDimStride0 = unrollDimStrideA
    kernel.unrollDimStride1 = unrollDimStrideB
  else:
    kernel.unrollDimStrideGreaterThanTileDimStrideA = \
      unrollDimStrideA > strideD1
    kernel.unrollDimStrideLessThanTileDimStrideB = \
      unrollDimStrideB < strideD0
    kernel.unrollDimStride0 = unrollDimStrideB
    kernel.unrollDimStride1 = unrollDimStrideA

  # print kernel name
  #kw = KernelWriter.KernelWriter(0)
  #print kw.getName(kernel)
  #print "\n"



################################################################################
# Main
################################################################################
if __name__ == "__main__":

  # arguments
  ap = argparse.ArgumentParser(description="FileReader")
  ap.add_argument("--input-file", dest="inputFiles", action="append" )
  args = ap.parse_args()

  # parse xml
  for inputFile in args.inputFiles:
    problemSet = set()
    FileReader.getProblemsFromXML( inputFile, problemSet )

  """print "numUnrolls = " + str(len(SolutionCandidates.universeUnroll))
  print "numWorkGroups = " + str(len(SolutionCandidates.universeWorkGroupDim))
  print "numMicroTiles = " + str(SolutionCandidates.maxMicroTileSize \
      * SolutionCandidates.maxMicroTileSize)"""

  solutionCandidates = SolutionCandidates()

  for problem in problemSet:
    solutionCandidatesForProblem = \
        solutionCandidates.getSolutionCandidatesForProblem( problem )
    print "\n"
    print problem
    print "\n\n"
    print len(solutionCandidatesForProblem)
    print solutionCandidatesForProblem
    break


